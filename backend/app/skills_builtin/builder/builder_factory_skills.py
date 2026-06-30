"""v6 · Builder-only factory skills.

替代 Builder LLM 必须按顺序调 5-6 个 tool 创建 super 的老模式 ——
LLM 现在只生成 spec_json，一次 tool call 一气呵成。

Skills:
- build_super(spec_json: dict) → {ok, super_agent_id, mission_id, slug, project_url}
- build_worker(spec_json: dict) → {ok, worker_agent_id, capability, slug}
"""
from __future__ import annotations

import json
import logging
import uuid

from langchain_core.tools import StructuredTool

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


async def _acquire_or_reject(ctx: BuiltinToolContext, target_type: str, target_id: str) -> str | None:
    """ADR-009 G4 · 改 target 前抢锁。被其它 session 持有 → 返回 reject JSON（调用方应直接返回它）；
    可获取/复用 → 返回 None（继续）。ctx 无 session_id 时跳过（不阻塞非 session 场景）。"""
    if ctx.mission_id is None or ctx.db_factory is None:
        return None
    from app.services import builder_claim_service
    async with ctx.db_factory() as db:
        res = await builder_claim_service.acquire_claim(
            db, target_type=target_type, target_id=target_id,
            session_id=ctx.mission_id, mission_id=ctx.mission_id,
        )
    if res.get("outcome") == "reject":
        return json.dumps({"ok": False, "error": "claim_conflict", "message": res["message"]}, ensure_ascii=False)
    return None


async def _record_work(
    ctx: BuiltinToolContext, *, action: str, target_type: str, target_id: str,
    result: str = "ok", summary: str = "", affected_supers: list | None = None,
) -> None:
    """ADR-009 G5 · 写一行 Builder 工作记录（per session 审计）。不阻塞主流程。"""
    if ctx.mission_id is None or ctx.db_factory is None:
        return
    try:
        from app.models.builder_governance import BuilderWorkLog
        async with ctx.db_factory() as db:
            db.add(BuilderWorkLog(
                session_id=ctx.mission_id, mission_id=ctx.mission_id,
                action=action, target_type=target_type, target_id=target_id,
                affected_supers=affected_supers or [], result=result, summary=summary[:2000],
            ))
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("[builder_work_log] 写工作记录失败（不阻塞）")


def build_super_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _build(spec_json: dict) -> str:
        """v6 · 一次性创建 SuperAgent + 它的 Mission + 必需 skill + optional schedule。

        spec_json 字段：
          name, slug, model_id (UUID str), description?, soul_md?, protocol_md?,
          goal_spec={description, completion_criteria?, must_have_capabilities?},
          capabilities (list[str]), skills (list[str]?),
          schedule={kind, expr, payload_template?}?, approval_channel?,
          max_iterations?, temperature?, enable_thinking?, extra_config?
        """
        from app.domain.builder import SuperSpec, apply_super_spec
        from app.skills_builtin.llm.llm_skills import resolve_model_id

        if ctx.db_factory is None:
            return json.dumps({"ok": False, "error": "缺 db_factory"})

        # resolve model_id（接受 UUID / "provider/model" / bare model_id）
        async with ctx.db_factory() as db:
            resolved = await resolve_model_id(db, str(spec_json.get("model_id", "")))
        if resolved is None:
            return json.dumps({"ok": False, "error": f"model_id 无法解析: {spec_json.get('model_id')!r}"})
        spec_payload = {**spec_json, "model_id": str(resolved)}

        try:
            spec = SuperSpec(**spec_payload)
        except Exception as e:
            return json.dumps({"ok": False, "error": f"spec 校验失败: {e}"}, ensure_ascii=False)

        # ADR-009 G4 · 抢 super:slug 锁（防多 session 并发改同一 super）
        reject = await _acquire_or_reject(ctx, "super", str(spec.slug))
        if reject is not None:
            return reject

        # created_by：从 ctx 拿 acting_user_id；缺则用 super_id
        actor = (ctx.extra or {}).get("acting_user_id") or (ctx.extra or {}).get("agent_id")
        if actor is None:
            return json.dumps({"ok": False, "error": "ctx 缺 acting_user_id；无法记 created_by"})
        try:
            actor_uuid = uuid.UUID(str(actor))
        except (ValueError, TypeError):
            return json.dumps({"ok": False, "error": f"actor not uuid: {actor!r}"})

        try:
            async with ctx.db_factory() as db:
                # 幂等：本 builder 设计会话已建过 super → 复用，绝不重建第二个
                from app.domain.builder.factory import existing_super_for_builder_mission
                existing = await existing_super_for_builder_mission(db, ctx.mission_id)
                if existing is not None:
                    from sqlalchemy import select as _select
                    from app.models.mission import Mission as _M
                    exm = (await db.execute(
                        _select(_M.slug).where(_M.supervisor_agent_id == existing.id).limit(1)
                    )).scalar()
                    return json.dumps({
                        "ok": True, "reused": True, "super_agent_id": str(existing.id),
                        "slug": existing.slug or exm or "",
                        "note": "本设计会话已建过 super，复用（单-super 幂等）。",
                    }, ensure_ascii=False)
                ref = await apply_super_spec(db, spec, created_by=actor_uuid)
                # 记 provenance（built_by_mission_id）：让幂等下次生效 + super 自迭代/escalation 路由
                if ctx.mission_id is not None:
                    from app.models.agent import Agent as _A
                    ag = await db.get(_A, ref.agent_id)
                    if ag is not None and ag.built_by_mission_id is None:
                        ag.built_by_mission_id = ctx.mission_id
                        await db.commit()
        except Exception as e:
            from app.domain.builder.spec_validation import MissingSkillsError
            logger.exception("[build_super] factory failed")
            await _record_work(ctx, action="build_super", target_type="super",
                               target_id=str(spec.slug), result="blocked", summary=str(e)[:500])
            if isinstance(e, MissingSkillsError):
                # ADR-009 G6 · 优雅降级：给 Builder 结构化的 missing + 下一步选项，别死循环
                return json.dumps({
                    "ok": False, "error_kind": "missing_skills", "missing_skills": e.missing,
                    "hint": "先用 create_skill_from_template（白名单模板）或 install_skill（ClawHub）补齐这些 skill，再重试 build_super；若都无法满足，向用户说明并求助。",
                }, ensure_ascii=False)
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

        await _record_work(ctx, action="build_super", target_type="super",
                           target_id=ref.slug, result="ok",
                           summary=f"创建 super {ref.slug}（capabilities={spec.capabilities}）")
        return json.dumps({
            "ok": True,
            "super_agent_id": str(ref.agent_id),
            "mission_id": str(ref.mission_id),
            "slug": ref.slug,
            "project_url": f"/super/{ref.slug}",
            "claim_hint": "完成对该 super 的处理后请调 release_work_claim 释放锁。",
        }, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_build,
        name="build_super",
        description=(
            "（Builder-only v6）一次性创建 SuperAgent + Mission + 必需 skill + 可选 schedule。"
            "spec_json: {name, slug, model_id, goal_spec, capabilities, schedule?, approval_channel?, "
            "soul_md?, protocol_md?, max_iterations?, temperature?, enable_thinking?, skills?, extra_config?}"
            "替代老的 agent_create→agent_update→5×skill_bind→mission_create→schedule_create→lifecycle 6 步链。"
        ),
    )


def build_worker_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _build(spec_json: dict) -> str:
        """v6 · 一次性创建/升级 WorkerAgent（平台共享）。

        spec_json 字段：
          name, slug, capability (slug), model_id, capability_contract={...},
          description?, soul_md?, protocol_md?, skills (list[str])?,
          needs_mcp?, max_iterations?, temperature?, extra_config?
        """
        from app.domain.builder import WorkerSpec, apply_worker_spec
        from app.skills_builtin.llm.llm_skills import resolve_model_id

        if ctx.db_factory is None:
            return json.dumps({"ok": False, "error": "缺 db_factory"})

        async with ctx.db_factory() as db:
            resolved = await resolve_model_id(db, str(spec_json.get("model_id", "")))
            if resolved is None:
                return json.dumps({"ok": False, "error": f"model_id 无法解析: {spec_json.get('model_id')!r}"})
            # aux_models 里的 model 可写成 UUID 或 'provider/model' 字符串（与主 model_id 一致）→ 统一解析成 UUID。
            # 接受 model / model_id 两种键名，兼容 list_models 返回的 model_id 字段直接粘进来。
            raw_aux = spec_json.get("aux_models") or []
            resolved_aux: list[dict] = []
            for aux in raw_aux:
                ref_str = str(aux.get("model_id") or aux.get("model") or "")
                aux_uuid = await resolve_model_id(db, ref_str)
                if aux_uuid is None:
                    return json.dumps({
                        "ok": False,
                        "error": (
                            f"aux_models 里的 model 无法解析: {ref_str!r}。"
                            "先 list_models(model_type='image'/'video'/'embedding') 拿正确的 model_id。"
                        ),
                    }, ensure_ascii=False)
                resolved_aux.append({
                    "role": aux.get("role", "custom"),
                    "model_id": str(aux_uuid),
                    "alias": aux.get("alias"),
                })
        spec_payload = {**spec_json, "model_id": str(resolved), "aux_models": resolved_aux}

        try:
            spec = WorkerSpec(**spec_payload)
        except Exception as e:
            return json.dumps({"ok": False, "error": f"spec 校验失败: {e}"}, ensure_ascii=False)

        # ADR-009 G4 · 抢 worker:capability 锁（防多 session 并发改同一 worker）
        reject = await _acquire_or_reject(ctx, "worker", str(spec.capability))
        if reject is not None:
            return reject

        actor = (ctx.extra or {}).get("acting_user_id") or (ctx.extra or {}).get("agent_id")
        actor_uuid = None
        if actor:
            try:
                actor_uuid = uuid.UUID(str(actor))
            except (ValueError, TypeError):
                pass

        try:
            async with ctx.db_factory() as db:
                ref = await apply_worker_spec(db, spec, created_by=actor_uuid)
        except Exception as e:
            # 跨 super 硬阻断 / 兼容失败 / 缺 skill 也走这里：把错误回给 Builder LLM + 记审计
            from app.domain.builder.spec_validation import MissingSkillsError
            logger.exception("[build_worker] factory failed")
            await _record_work(ctx, action="build_worker", target_type="worker",
                               target_id=str(spec.capability), result="blocked", summary=str(e)[:1000])
            if isinstance(e, MissingSkillsError):
                return json.dumps({
                    "ok": False, "error_kind": "missing_skills", "missing_skills": e.missing,
                    "hint": "先用 create_skill_from_template 或 install_skill 补齐这些 skill 再重试 build_worker。",
                }, ensure_ascii=False)
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

        # 记录影响了哪些 super（升级共享 worker 的审计）
        affected: list = []
        try:
            from app.domain.builder.capability_consumers import find_supers_using_capability
            async with ctx.db_factory() as db:
                cons = await find_supers_using_capability(db, spec.capability)
            affected = [c["super_slug"] for c in cons]
        except Exception:  # noqa: BLE001
            pass
        await _record_work(ctx, action="build_worker", target_type="worker",
                           target_id=ref.capability, result="ok", affected_supers=affected,
                           summary=f"创建/升级 worker capability={ref.capability}；影响 super={affected}")
        return json.dumps({
            "ok": True,
            "worker_agent_id": str(ref.agent_id),
            "capability": ref.capability,
            "slug": ref.slug,
            "affected_supers": affected,
            "claim_hint": "完成对该 worker 的处理后请调 release_work_claim 释放锁。",
        }, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_build,
        name="build_worker",
        description=(
            "（Builder-only v6）一次性创建/升级 WorkerAgent（平台共享，按 capability upsert）。"
            "spec_json: {name, slug, capability, model_id, capability_contract, soul_md?, "
            "protocol_md?, skills?, needs_mcp?, max_iterations?, temperature?, extra_config?, aux_models?}"
            "替代 agent_create→agent_update→skill_bind→…的 4 步链。"
            "🖼️ 图片/视频/embedding worker：在 aux_models 里带绑定，建 worker 时一并落库，"
            "无需再单独调 agent_aux_model_bind。"
            "aux_models=[{role:'image'|'video'|'embedding'|..., model:'<UUID 或 provider/model>', alias?}]；"
            "先 list_models(model_type='image') 拿 model。worker protocol 里用 invoke_aux_model(alias_or_role='image') 出图。"
            "⚠️ 升级既有 worker 会自动跑跨 super 兼容硬阻断：若新契约破坏任一在用它的 super 则报错回滚。"
            "完成后请调 release_work_claim 释放该 worker 的处理锁。"
        ),
    )


def create_skill_from_template_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _create(template: str, slug: str, name: str, config: dict) -> str:
        """ADR-009 G6 ·（Builder-only）从白名单模板创建一个新 skill（不跑任意代码）。

        模板：http_api_call(config: method,url_template,headers?) /
              mcp_proxy(config: mcp_server_id,tool_name) /
              prompt_macro(config: prompt_template,role?)。
        创建后该 slug 即存在，build_super/build_worker 的缺-skill 硬门即可通过。
        """
        from sqlalchemy import select as _select
        from app.domain.builder.skill_template import render_skill_row, validate_template_request
        from app.models.skill import Skill

        if ctx.db_factory is None:
            return json.dumps({"ok": False, "error": "缺 db_factory"})
        err = validate_template_request(template=template, slug=slug, config=config or {})
        if err:
            return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
        row = render_skill_row(template=template, slug=slug, name=name, config=config or {})
        async with ctx.db_factory() as db:
            exists = (await db.execute(_select(Skill).where(Skill.slug == slug))).scalar_one_or_none()
            if exists is not None:
                return json.dumps({"ok": True, "slug": slug, "already_exists": True}, ensure_ascii=False)
            db.add(Skill(
                slug=row["slug"], name=row["name"], description=f"模板生成({template})",
                skill_type=row["skill_type"], builtin_ref=row["builtin_ref"],
                config_schema=row["config"], is_enabled=True, is_builtin=False,
                scope="all", intent="io",
            ))
            await db.commit()
        await _record_work(ctx, action="create_skill", target_type="skill", target_id=slug,
                           result="ok", summary=f"模板 {template} 生成 skill {slug}")
        return json.dumps({"ok": True, "slug": slug, "template": template}, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_create,
        name="create_skill_from_template",
        description=(
            "（Builder-only ADR-009）从白名单模板创建新 skill（不跑任意代码）。"
            "template ∈ {http_api_call, mcp_proxy, prompt_macro}；slug/name/config。"
            "用于 build_* 报 missing_skills 时补齐缺失 skill。"
        ),
    )


def release_work_claim_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _release(target_type: str, target_id: str) -> str:
        """ADR-009 G4 ·（Builder-only）处理完某 worker/super/skill 后释放本 session 的处理锁，
        让其它 session 可以接手。target_type ∈ {worker, super, skill}；target_id = capability / slug。"""
        if ctx.mission_id is None or ctx.db_factory is None:
            return json.dumps({"ok": False, "error": "缺 session_id / db_factory"})
        from app.services import builder_claim_service
        async with ctx.db_factory() as db:
            res = await builder_claim_service.release_claim(
                db, target_type=target_type, target_id=target_id, session_id=ctx.mission_id,
            )
        return json.dumps(res, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_release,
        name="release_work_claim",
        description=(
            "（Builder-only）处理完某 worker/super/skill 后释放处理锁。"
            "target_type ∈ {worker, super, skill}, target_id = capability slug / project slug。"
        ),
    )
