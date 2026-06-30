"""ADR-009 G1 · 谁在用某 capability（CapabilityConsumer 查询）。

worker 平台共享，改契约前必须知道「哪些 super 在依赖它」。两路合并：
- 声明用量：agent.extra_config.required_capabilities 含该 capability 的 super
- 观测用量：worker_invocation_log 近 window_days 内调用过该 worker 的 super（精确到 action）

返回 [{super_agent_id, super_slug, mission_id, used_actions, source}]，喂给
spec_validation.analyze_worker_change_impact 做跨 super 影响分析（硬阻断依据）。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _all_actions(contract: dict | None) -> list[str]:
    if not contract:
        return []
    return [
        a.get("action")
        for a in (contract.get("advertises") or [])
        if isinstance(a, dict) and a.get("action")
    ]


async def find_supers_using_capability(
    db: AsyncSession,
    capability: str,
    *,
    old_contract: dict | None = None,
    window_days: int = 30,
) -> list[dict]:
    """找出在用 capability 的 super（声明 ∪ 观测）。

    声明-only（声明了但无调用记录）的 super 保守起见按「用了旧契约全部 action」处理，
    确保删任何 action 都会被它挡下（安全优先，符合「不能一边好一边坏」）。
    """
    from app.models.agent import Agent
    from app.models.mission import Mission

    # ── 观测用量：worker_invocation_log（表可能在某些测试库不存在，guard 起来）──
    observed: dict[str, set[str]] = {}
    observed_project: dict[str, str] = {}
    try:
        rows = (await db.execute(
            text(
                """
                SELECT CAST(wil.super_agent_id AS TEXT) AS sid,
                       CAST(wil.super_mission_id AS TEXT) AS pid,
                       wil.action AS action
                  FROM worker_invocation_log wil
                  JOIN agents a ON a.id = wil.worker_agent_id
                 WHERE a.capability = :cap
                   AND wil.started_at >= now() - make_interval(days => :days)
                """
            ),
            {"cap": capability, "days": window_days},
        )).mappings().all()
        for r in rows:
            sid = r["sid"]
            if not sid:
                continue
            observed.setdefault(sid, set())
            if r["action"]:
                observed[sid].add(r["action"])
            if r["pid"]:
                observed_project[sid] = r["pid"]
    except Exception:  # noqa: BLE001 —— 表缺失/方言差异不阻塞（退化为只看声明用量）
        logger.debug("[capability_consumers] 观测用量查询失败（退化为声明用量）", exc_info=True)

    # ── 声明用量：扫 super agents 的 extra_config.required_capabilities（dialect-agnostic）──
    # 只取需要的列，避免 ORM 实体触发 mcp_servers 等关系的 eager-load。
    declared_ids: set[str] = set()
    super_name_by_id: dict[str, str] = {}
    rows2 = (await db.execute(
        select(Agent.id, Agent.name, Agent.extra_config).where(Agent.kind == "super")
    )).all()
    for sup_id, sup_name, extra in rows2:
        super_name_by_id[str(sup_id)] = sup_name or ""
        caps = (extra or {}).get("required_capabilities") or []
        if capability in caps:
            declared_ids.add(str(sup_id))

    all_old_actions = _all_actions(old_contract)

    # ── 解析 super → project slug ──
    all_super_ids = set(observed.keys()) | declared_ids
    if not all_super_ids:
        return []
    proj_rows = (await db.execute(
        select(Mission.id, Mission.slug, Mission.supervisor_agent_id).where(
            Mission.supervisor_agent_id.in_([uuid.UUID(x) for x in all_super_ids])
        )
    )).all()
    slug_by_super: dict[str, tuple[str, str]] = {
        str(sup_id): (slug, str(pid)) for pid, slug, sup_id in proj_rows
    }

    return _build_consumers(
        all_super_ids, observed, declared_ids, observed_project,
        slug_by_super, super_name_by_id, all_old_actions,
    )


async def govern_worker_contract_change(
    db: AsyncSession, *, capability: str, slug: str,
    old_contract: dict | None, new_contract: dict,
) -> None:
    """ADR-009 · 改 worker 契约的统一治理闸门（apply_worker_spec + agent_update 共用）。

    依次：① 结构校验 ② 自洽向下兼容 ③ 跨 super 影响硬阻断。任一不过抛 ValueError（调用方回滚）。
    新建 worker（old_contract 空）只校结构。
    """
    from app.domain.builder.spec_validation import (
        analyze_worker_change_impact, check_backward_compat, validate_capability_contract,
    )

    violations = validate_capability_contract(new_contract or {})
    if violations:
        raise ValueError(
            f"worker「{slug}」capability_contract 不合规（已回滚）:\n- " + "\n- ".join(violations)
        )
    if not (old_contract or {}).get("advertises"):
        return  # 新建 / 旧无契约 → 无消费方，结构 OK 即可

    compat = check_backward_compat(old_contract, new_contract or {})
    if not compat["compatible"]:
        raise ValueError(
            f"worker「{slug}」升级破坏向下兼容（已回滚）:\n- " + "\n- ".join(compat["violations"])
            + "\n如确需弃用旧 action，请加入 deprecated_actions 后再升级。"
        )
    consumers = await find_supers_using_capability(db, capability, old_contract=old_contract)
    impact = analyze_worker_change_impact(
        old_contract=old_contract, new_contract=new_contract or {}, consumers=consumers,
    )
    if not impact["safe"]:
        lines = [
            f"  · super「{b['super_slug']}」断在 action {b['broken_actions']}：" + "；".join(b["reasons"])
            for b in impact["breaking"]
        ]
        raise ValueError(
            f"worker「{slug}」升级会破坏 {len(impact['breaking'])} 个在用它的 super"
            f"（已回滚，杜绝「一边好一边坏」）:\n" + "\n".join(lines)
            + "\n请改成兼容升级（保留旧 action / 只加 optional 输入 / 不删 output），或先升级这些 super 再改 worker。"
        )


def _build_consumers(all_super_ids, observed, declared_ids, observed_project,
                     slug_by_super, super_name_by_id, all_old_actions) -> list[dict]:
    consumers: list[dict] = []
    for sid in all_super_ids:
        slug, pid = slug_by_super.get(sid, ("", observed_project.get(sid, "")))
        if sid in observed and observed[sid]:
            used = sorted(observed[sid])
            source = "observed"
        elif sid in declared_ids:
            # 声明-only：保守按全部旧 action 处理
            used = list(all_old_actions)
            source = "declared"
        else:
            # 观测到但无 action（理论少见）→ 保守全 action
            used = list(all_old_actions)
            source = "observed"
        consumers.append({
            "super_agent_id": sid,
            "super_slug": slug or super_name_by_id.get(sid) or sid[:8],
            "mission_id": pid,
            "used_actions": used,
            "source": source,
        })
    return consumers
