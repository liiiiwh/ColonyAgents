"""AgentFactory · v6.

把 Builder LLM 6+ tool 编排（agent_create → agent_update → 5×skill_bind → mission_create
→ schedule_create → lifecycle_start）合并成 1 个事务化 apply_super_spec / apply_worker_spec。

依赖既有 service：
- agent_service.create_agent / update_agent
- mission_service.create_mission
- scheduler_service.reschedule_one

事务边界：
- 单 session.begin() 包住所有 SQL；中间任何 raise → 全部 rollback
- skill binding 用 AgentSkill 直插，不走 agent_service.add_skill 的独立 commit
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# super 必需 skill slug —— Builder 设计 super 时一定要这些
SUPER_REQUIRED_SKILLS = [
    "invoke_worker",
    "invoke_workers_parallel",
    "list_workers",
    "request_new_capability",
    "request_approval",
    "memory_read",
    "memory_write",
    "memory_append",
    "knowledge_search",
    "record_decision",
    # ADR-024 S4 · super 自管调度（自迭代调节奏，护栏在 schedule_create_tool）
    "schedule_create",
    "schedule_update",
    "schedule_delete",
]

WORKER_DEFAULT_SKILLS = [
    "return_result",
]


async def existing_super_for_builder_mission(db: AsyncSession, mission_id):
    """单-super 幂等：若 mission_id 是「Builder super 监管的设计会话」（主 builder mission
    或用户 +新建 的每场景会话）且已 built_by 出一个 super → 返回它，供 build_super/agent_create
    复用、绝不重建第二个。判定 supervisor 为 category='builder' 的 super（不再只认 slug=='builder'）。
    无则 None。"""
    from app.models.agent import Agent
    from app.models.mission import Mission

    if mission_id is None:
        return None
    proj = await db.get(Mission, mission_id)
    if proj is None or proj.supervisor_agent_id is None:
        return None
    sup = await db.get(Agent, proj.supervisor_agent_id)
    if sup is None or sup.category != "builder":
        return None
    return (await db.execute(
        select(Agent).where(Agent.kind == "super", Agent.built_by_mission_id == mission_id)
    )).scalars().first()


@dataclass(frozen=True)
class SuperRef:
    agent_id: uuid.UUID
    mission_id: uuid.UUID
    slug: str


@dataclass(frozen=True)
class WorkerRef:
    agent_id: uuid.UUID
    slug: str
    capability: str


@dataclass(frozen=True)
class MissionRef:
    """v6 · spawn_mission 返回；Mission = 既有 super 的一次实例化（= 一个 Mission row）。"""
    mission_id: uuid.UUID
    super_agent_id: uuid.UUID
    slug: str


_SLUG_RE = __import__("re").compile(r"[^a-z0-9]+")


def _slugify_mission(name: str) -> str:
    """从中文/英文 mission name 生成 url-safe slug；末尾加 6 字符 hash 防冲突。"""
    import hashlib, time
    base = _SLUG_RE.sub("-", name.lower().strip()).strip("-")[:32]
    if not base or not base[0].isalnum():
        base = "mission"
    suffix = hashlib.sha1(f"{name}{time.time()}".encode("utf-8")).hexdigest()[:6]
    return f"{base}-{suffix}"


async def spawn_mission(
    db: AsyncSession,
    *,
    super_agent_id: uuid.UUID,
    name: str,
    created_by: uuid.UUID,
    goal_hint: str | None = None,
) -> MissionRef:
    """v6.A · 用既有 SuperAgent 创建一个新 Mission（= Mission row）。

    跟 apply_super_spec 的区别：
      - apply_super_spec 创建 SuperAgent **角色 + 第一个 Mission**（建新 super）
      - spawn_mission 复用既有 SuperAgent → 只建 Mission row（同 super 可被 N mission 引用）

    用户体验对应：在 /super/<slug> 页点「+ 新建 Mission」时调本函数。
    goal_hint 写到 project.workflow_config.goal_hint；super 第一次 tick 会读它启动 goal_spec
    收集流程。
    """
    from app.models.agent import Agent
    from app.models.mission import Mission

    agent = await db.get(Agent, super_agent_id)
    if agent is None:
        raise ValueError(f"super_agent_id={super_agent_id} 不存在")
    if agent.kind != "super":
        raise ValueError(f"agent.kind={agent.kind!r}，spawn_mission 只接受 kind='super'")

    workflow_config: dict = {}
    if goal_hint:
        workflow_config["goal_hint"] = goal_hint

    # ADR-026 D1/D2 · 新 mission 的「全自动·完全授权」默认值，create-time 从 super 快照一次：
    # super.extra_config.mission_default_auto_approve 缺省 True（全局默认全自动）；
    # 唯独 Builder super 种子设 False，让设计会话回到 propose-confirm 人审。
    # 之后改 super 这个开关不回溯已建 mission（单 mission 由 AutoApproveToggle 实时控）。
    default_auto_approve = bool((agent.extra_config or {}).get("mission_default_auto_approve", True))

    slug = _slugify_mission(name)
    project = Mission(
        name=name,
        description="",
        slug=slug,
        supervisor_agent_id=super_agent_id,
        created_by=created_by,
        workflow_config=workflow_config,
        auto_approve=default_auto_approve,
    )
    db.add(project)
    await db.flush()
    mission_id = project.id
    await db.commit()
    # ADR-023 S7 · 建 per-super 共享 KB（幂等：同 super 已有则复用）
    try:
        from app.services.mission_service import _ensure_mission_kb
        await _ensure_mission_kb(db, project, created_by)
    except Exception:
        logger.warning("[spawn_mission] KB 建失败（不阻塞）", exc_info=True)
    return MissionRef(
        mission_id=mission_id,
        super_agent_id=super_agent_id,
        slug=slug,
    )


async def apply_super_spec(db: AsyncSession, spec: "SuperSpec",
                           *, created_by: uuid.UUID) -> SuperRef:
    """事务化创建一个 SuperAgent + 它的 Mission + optional schedule。

    幂等：若 slug 已存在的 Mission，则视作 update（只改 agent / re-bind skills，不动 mission_id）。
    """
    from app.domain.builder import SuperSpec
    from app.models.agent import Agent, AgentSkill
    from app.models.mission import Mission
    from app.models.skill import Skill

    assert isinstance(spec, SuperSpec)

    # ADR-008 P5 · 硬门（前置 fail-fast）：请求的 skill 不存在 → 抛错不静默跳过，
    # 且在建 agent/project 之前就拦掉（不产生任何残留写入）。
    must_have = set(SUPER_REQUIRED_SKILLS) | set(spec.skills or [])
    super_skill_rows = (await db.execute(
        select(Skill).where(Skill.slug.in_(must_have))
    )).scalars().all() if must_have else []
    from app.domain.builder.spec_validation import MissingSkillsError, missing_skills
    miss = missing_skills(must_have, {s.slug for s in super_skill_rows})
    if miss:
        raise MissingSkillsError(miss, agent_kind="super", slug=spec.slug)

    # 1. upsert agent
    existing_proj = (await db.execute(
        select(Mission).where(Mission.slug == spec.slug)
    )).scalar_one_or_none()

    if existing_proj is not None:
        agent = await db.get(Agent, existing_proj.supervisor_agent_id)
        if agent is None:
            raise ValueError(f"project {spec.slug} 存在但 supervisor_agent_id 指向空")
        # update
        agent.name = spec.name
        agent.slug = spec.slug  # super 身份 slug（URL）
        agent.display_name = spec.name  # 人读显示名（标题）
        agent.description = spec.description
        agent.model_id = spec.model_id
        agent.soul_md = spec.soul_md
        agent.protocol_md = spec.protocol_md
        agent.max_iterations = spec.max_iterations
        agent.temperature = spec.temperature
        agent.enable_thinking = spec.enable_thinking
        agent.kind = "super"
        agent.extra_config = spec.to_extra_config()
        project = existing_proj
        project.name = spec.name
        project.description = spec.description
    else:
        agent = Agent(
            name=spec.name,
            slug=spec.slug,  # super 身份 slug（URL）
            display_name=spec.name,  # 人读显示名（标题）
            description=spec.description,
            category="custom",
            kind="super",
            model_id=spec.model_id,
            soul_md=spec.soul_md,
            protocol_md=spec.protocol_md,
            max_iterations=spec.max_iterations,
            temperature=spec.temperature,
            enable_thinking=spec.enable_thinking,
            extra_config=spec.to_extra_config(),
        )
        db.add(agent)
        await db.flush()  # 拿 agent.id

        project = Mission(
            name=spec.name,
            description=spec.description,
            slug=spec.slug,
            supervisor_agent_id=agent.id,
            created_by=created_by,
        )
        db.add(project)
        await db.flush()  # 拿 project.id

    # 2. 绑必需 super skills（幂等：已有不重复）—— 复用前置 fail-fast 已校验过的 super_skill_rows
    if super_skill_rows:
        existing_bindings = (await db.execute(
            select(AgentSkill.skill_id).where(AgentSkill.agent_id == agent.id)
        )).scalars().all()
        already = set(existing_bindings)
        for sk in super_skill_rows:
            if sk.id not in already:
                db.add(AgentSkill(agent_id=agent.id, skill_id=sk.id, config={}))

    # 3. optional schedule
    if spec.schedule:
        from app.models.mission import MissionSchedule
        # 简化：每次都新建 cron schedule；幂等可后续做
        sched_kind = spec.schedule.get("kind", "cron")
        sched_expr = spec.schedule.get("expr", "*/3 * * * *")
        sched_name = spec.schedule.get("name", f"{spec.slug}_default")
        existing_sched = (await db.execute(
            select(MissionSchedule).where(
                MissionSchedule.mission_id == project.id,
                MissionSchedule.name == sched_name,
            )
        )).scalar_one_or_none()
        if existing_sched is None:
            db.add(MissionSchedule(
                mission_id=project.id,
                name=sched_name,
                kind=sched_kind,
                expr=sched_expr,
                payload_template=spec.schedule.get("payload_template") or {},
                enabled=True,
                created_by=created_by,
            ))

    # 4. optional approval channel
    if spec.approval_channel:
        from app.models.approvals import MissionApprovalChannel
        existing_chan = (await db.execute(
            select(MissionApprovalChannel).where(MissionApprovalChannel.mission_id == project.id)
        )).scalar_one_or_none()
        if existing_chan is None:
            db.add(MissionApprovalChannel(
                mission_id=project.id,
                clawbot_account_id=spec.approval_channel.get("clawbot_account_id"),
                reviewer_wechat_ids=spec.approval_channel.get("reviewer_wechat_ids") or [],
                enabled=True,
            ))

    await db.commit()
    return SuperRef(agent_id=agent.id, mission_id=project.id, slug=spec.slug)


async def persist_contract_aux_models(db: AsyncSession, agent_id, capability_contract: dict) -> int:
    """把 `capability_contract.aux_models` 落到 `agent_aux_models` 表（运行时 `_resolve_binding` 读这里）。

    回归 e2e 抓到的真 bug：Builder 的 build-then-`agent_update(capability_contract={..,aux_models})` 流
    只把绑定写进 `extra_config.capability_contract`，表里空 → `invoke_aux_model(role='image')` 找不到
    binding →「未找到辅助模型」出不了图。本函数把 contract 里声明的 aux 绑定 materialize 到表，
    让表保持运行时唯一真源。`model_id` 可为 UUID 或 'provider/model'。不 commit（调用方负责）。
    返回落库/更新条数；模型不存在/停用 → 抛 ValueError（调用方据此回滚）。
    """
    aux_list = (capability_contract or {}).get("aux_models") or []
    if not aux_list:
        return 0
    from app.models.agent import AgentAuxModel
    from app.models.provider import LLMModel
    from app.skills_builtin.llm.llm_skills import resolve_model_id

    n = 0
    for aux in aux_list:
        ref = str(aux.get("model_id") or aux.get("model") or "").strip()
        if not ref:
            continue
        mid = await resolve_model_id(db, ref)
        if mid is None:
            raise ValueError(
                f"aux model {ref!r} 无法解析（先 list_models(model_type='image'/'video'/'embedding') 拿 UUID）"
            )
        m = await db.get(LLMModel, mid)
        if m is None:
            raise ValueError(f"aux model {ref!r} 不存在")
        if not m.is_enabled:
            raise ValueError(f"aux model {m.model_id} 已停用，不能绑定")
        existing = await db.get(AgentAuxModel, (agent_id, mid))
        if existing is not None:
            existing.role = aux.get("role") or existing.role
            existing.alias = aux.get("alias")
        else:
            db.add(AgentAuxModel(
                agent_id=agent_id, model_id=mid,
                role=aux.get("role") or "image", alias=aux.get("alias"), config={},
            ))
        n += 1
    return n


async def apply_worker_spec(db: AsyncSession, spec: "WorkerSpec",
                            *, created_by: uuid.UUID | None = None) -> WorkerRef:
    """事务化创建/升级一个 WorkerAgent（平台共享）。

    幂等：按 capability slug upsert。
    """
    from app.domain.builder import WorkerSpec
    from app.models.agent import Agent, AgentSkill
    from app.models.skill import Skill

    assert isinstance(spec, WorkerSpec)

    # ADR-008 P5 · 硬门 1：capability_contract 结构校验（advertises 每项必有 action+side_effects+requires_approval）
    from app.domain.builder.spec_validation import MissingSkillsError, missing_skills
    from app.domain.builder.capability_consumers import govern_worker_contract_change

    existing = (await db.execute(
        select(Agent).where(Agent.kind == "worker", Agent.capability == spec.capability)
    )).scalar_one_or_none()

    # ADR-008 P5 + ADR-009 G1 · 统一治理闸门：结构校验 + 自洽向下兼容 + 跨 super 影响硬阻断
    old_contract = (existing.extra_config or {}).get("capability_contract") if existing else None
    await govern_worker_contract_change(
        db, capability=spec.capability, slug=spec.slug,
        old_contract=old_contract, new_contract=spec.capability_contract or {},
    )

    if existing is not None:
        agent = existing
        agent.name = spec.name
        agent.description = spec.description
        agent.model_id = spec.model_id
        agent.soul_md = spec.soul_md
        agent.protocol_md = spec.protocol_md
        agent.max_iterations = spec.max_iterations
        agent.temperature = spec.temperature
        agent.enable_thinking = spec.enable_thinking
        agent.extra_config = spec.to_extra_config()
    else:
        agent = Agent(
            name=spec.name,
            description=spec.description,
            category="worker.custom",
            kind="worker",
            capability=spec.capability,
            model_id=spec.model_id,
            soul_md=spec.soul_md,
            protocol_md=spec.protocol_md,
            max_iterations=spec.max_iterations,
            temperature=spec.temperature,
            enable_thinking=spec.enable_thinking,
            extra_config=spec.to_extra_config(),
        )
        db.add(agent)
        await db.flush()

    # bind 默认 worker skills + spec 指定
    # ADR-008 P5 · 硬门 3：缺 skill 报错不静默跳过
    must_have = set(WORKER_DEFAULT_SKILLS) | set(spec.skills or [])
    if must_have:
        skill_rows = (await db.execute(
            select(Skill).where(Skill.slug.in_(must_have))
        )).scalars().all()
        miss = missing_skills(must_have, {s.slug for s in skill_rows})
        if miss:
            raise MissingSkillsError(miss, agent_kind="worker", slug=spec.slug)
        existing_bindings = (await db.execute(
            select(AgentSkill.skill_id).where(AgentSkill.agent_id == agent.id)
        )).scalars().all()
        already = set(existing_bindings)
        for sk in skill_rows:
            if sk.id not in already:
                db.add(AgentSkill(agent_id=agent.id, skill_id=sk.id, config={}))

    # 辅助模型绑定（图像/视频/embedding）—— 与 worker 建库同事务落 AgentAuxModel，闭合
    # 「invoke_aux_model(role='image') 找得到 binding」的回路。直接 add（不走 agent_service.add_aux_model，
    # 那个会自行 commit，破坏本工厂的原子回滚不变式）。
    if spec.aux_models:
        from app.models.agent import AgentAuxModel
        from app.models.provider import LLMModel
        for aux in spec.aux_models:
            m = (await db.execute(
                select(LLMModel).where(LLMModel.id == aux.model_id)
            )).scalar_one_or_none()
            if m is None:
                raise ValueError(
                    f"aux model {aux.model_id} 不存在（先 list_models(model_type='image'/'video'/'embedding') 拿 UUID）"
                )
            if not m.is_enabled:
                raise ValueError(f"aux model {m.model_id} 已停用，不能绑定")
            existing_aux = await db.get(AgentAuxModel, (agent.id, aux.model_id))
            if existing_aux is not None:
                existing_aux.role = aux.role
                existing_aux.alias = aux.alias
            else:
                db.add(AgentAuxModel(
                    agent_id=agent.id, model_id=aux.model_id,
                    role=aux.role, alias=aux.alias, config={},
                ))

    await db.commit()

    # v6 · 同步刷新 worker_capability_actions 索引（PG-only）
    try:
        from app.domain.builder.capability_index import rebuild_for_worker
        await rebuild_for_worker(db, worker_agent_id=agent.id)
    except Exception:
        logger.exception("[apply_worker_spec] capability_index rebuild 失败 (不阻塞)")

    return WorkerRef(agent_id=agent.id, slug=spec.slug, capability=spec.capability)
