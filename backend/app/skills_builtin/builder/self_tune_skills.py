"""L2 · 项目自调优 (Self-Tune)。

设计目标：worker-project supervisor 在质量门（L1）verdict 连续失败时，
**提议 → 审批 → 应用 → 评估 → 自动回退** 修改 worker 的 protocol_md，
全部走 `agent_protocol_history` 留痕，不允许直接 `agent_update`。

4 个工具：
- `agent_protocol_propose`：写一行 proposal（pending），不改 agent；返回 proposal_id
- `agent_protocol_apply`：把 pending proposal 应用到 agent + 写 history + 抓 metrics_baseline
- `agent_protocol_revert`：回退到指定版本（默认上一版），插一行 history（rollback_of_version 非空）
- `agent_protocol_evaluate`：apply 后看 quality_gate pass-rate 变化，给 keep / revert 建议

护栏：
- H4 并发：DB 上 (agent_id) WHERE status='pending' 是 UNIQUE INDEX；propose 撞 unique 返回
  `superseded_by_existing`。expires_at 24h；scheduler 周期把过期的标 expired。
- H5 history 保留：服务层 prune 最近 20 版 + 永不删 `factory_initial` / `human_admin`。
- H15 supervisor 不能自调优：propose 内部校验 agent_id != 当前 supervisor agent_id。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.tools import StructuredTool
from sqlalchemy import desc, func, select

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


PROPOSAL_TTL_HOURS = 24
HISTORY_RETENTION_PER_AGENT = 20
APPLY_QUOTA_PER_AGENT_PER_24H = 3


async def _current_protocol_version(db, agent_id: uuid.UUID) -> int:
    """从 history 求当前 version（MAX）。0 = 从未调优过。"""
    from app.models.agent import AgentProtocolHistory
    res = await db.execute(
        select(func.coalesce(func.max(AgentProtocolHistory.version), 0)).where(
            AgentProtocolHistory.agent_id == agent_id
        )
    )
    return int(res.scalar() or 0)


async def _ensure_factory_initial_seeded(db, agent_id: uuid.UUID) -> int:
    """如果该 agent 没有任何 history 行，先种一条 factory_initial（version=0）。
    把 agent 当前 soul/protocol 快照固化，便于将来 revert。返回最新 version。"""
    from app.models.agent import Agent, AgentProtocolHistory
    existing = await _current_protocol_version(db, agent_id)
    if existing > 0:
        return existing
    # 看有没有 version=0 行
    res = await db.execute(
        select(AgentProtocolHistory).where(
            AgentProtocolHistory.agent_id == agent_id,
            AgentProtocolHistory.version == 0,
        )
    )
    if res.scalar_one_or_none():
        return 0
    agent = await db.get(Agent, agent_id)
    if agent is None:
        return -1
    row = AgentProtocolHistory(
        agent_id=agent_id,
        version=0,
        soul_md=agent.soul_md,
        protocol_md=agent.protocol_md,
        applied_at=datetime.now(UTC),
        applied_by_kind="factory_initial",
        applied_by_ref="auto-seed",
        trigger_summary="auto-seed on first propose/apply",
        rollback_of_version=None,
        metrics_baseline=None,
    )
    db.add(row)
    await db.commit()
    return 0


async def _prune_history(db, agent_id: uuid.UUID) -> int:
    """H5：保留最近 20 版 + 永不删 factory_initial / human_admin。返回剪掉的行数。"""
    from app.models.agent import AgentProtocolHistory
    rows = (
        await db.execute(
            select(AgentProtocolHistory)
            .where(AgentProtocolHistory.agent_id == agent_id)
            .order_by(desc(AgentProtocolHistory.version))
        )
    ).scalars().all()
    if len(rows) <= HISTORY_RETENTION_PER_AGENT:
        return 0
    keep_ids: set = set()
    keep_count = 0
    for r in rows:
        if keep_count < HISTORY_RETENTION_PER_AGENT:
            keep_ids.add(r.id)
            keep_count += 1
            continue
        if r.applied_by_kind in ("factory_initial", "human_admin"):
            keep_ids.add(r.id)
    deleted = 0
    for r in rows:
        if r.id not in keep_ids:
            await db.delete(r)
            deleted += 1
    if deleted:
        await db.commit()
    return deleted


def _diff_preview(old: str | None, new: str | None) -> str:
    """简单 diff preview：行级 +/-。≤500 字。"""
    if not old:
        return f"+ NEW (前无 protocol)\n{(new or '')[:400]}"
    if not new:
        return "- removed"
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    added = [l for l in new_lines if l not in old_lines]
    removed = [l for l in old_lines if l not in new_lines]
    parts = []
    for ln in removed[:5]:
        parts.append(f"- {ln[:100]}")
    for ln in added[:5]:
        parts.append(f"+ {ln[:100]}")
    if len(removed) > 5 or len(added) > 5:
        parts.append(f"... 共 +{len(added)} / -{len(removed)} 行")
    out = "\n".join(parts)
    return out[:500]


async def _quality_gate_pass_rate(
    db, mission_id: uuid.UUID | None, since_version: int = 0
) -> dict[str, Any]:
    """读 Mission(Mission).workspace 各节点的 quality_gate verdict 历史，算 pass-rate（pass / total）。
    返回 {samples: n, pass_rate: 0.0-1.0, breakdown: {pass,warn,block}}。
    ADR-018 step5/W：workspace 一个 Mission 一份，挂 Mission 上。
    """
    from app.models.mission import Mission
    if mission_id is None:
        return {"samples": 0, "pass_rate": 0.0, "breakdown": {}}
    proj = await db.get(Mission, mission_id)
    ws = (proj.workspace or {}) if proj else {}
    verdicts: list[str] = []
    for node_data in ws.values():
        if not isinstance(node_data, dict):
            continue
        state = node_data.get("state") or {}
        history = state.get("verdict_history") or []
        for v in history:
            if isinstance(v, dict) and v.get("verdict"):
                verdicts.append(v["verdict"])
    samples = len(verdicts)
    if samples == 0:
        return {"samples": 0, "pass_rate": 0.0, "breakdown": {}}
    passes = sum(1 for v in verdicts if v == "pass")
    breakdown = {
        "pass": sum(1 for v in verdicts if v == "pass"),
        "warn": sum(1 for v in verdicts if v == "warn"),
        "block": sum(1 for v in verdicts if v == "block"),
    }
    return {
        "samples": samples,
        "pass_rate": passes / samples,
        "breakdown": breakdown,
    }


async def _fetch_caller_stats(db, worker_id, *, since=None, until=None):
    """ADR-015 · 某 worker 在 [since, until) 窗口内逐 (super, action) 的成功率快照。

    用于跨调用方兼容门：apply 前/后各取一份，逐调用方比成功率，任一明显退化 → 不兼容。
    返回 list[CallerStat]。
    """
    from sqlalchemy import text as _sql_text

    from app.domain.optimization.compat_gate import CallerStat

    clauses = ["worker_agent_id = :wid"]
    params = {"wid": str(worker_id)}
    if since is not None:
        clauses.append("started_at >= :since")
        params["since"] = since
    if until is not None:
        clauses.append("started_at < :until")
        params["until"] = until
    rows = (await db.execute(_sql_text(f"""
        SELECT super_agent_id, action,
               COUNT(*) AS total,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed
          FROM worker_invocation_log
         WHERE {' AND '.join(clauses)}
         GROUP BY super_agent_id, action
    """), params)).mappings().all()
    return [
        CallerStat(super_agent_id=str(r["super_agent_id"]), action=r["action"],
                   total=int(r["total"]), completed=int(r["completed"]))
        for r in rows
    ]


# ── Tool factories ──
def agent_protocol_propose_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _propose(
        agent_id: str,
        new_protocol_md: str,
        diff_summary: str,
        trigger_summary: str,
        expected_improvement: str,
        new_soul_md: str = "",
    ) -> str:
        """L2 自调优：提议修改一个 worker 的 protocol_md，等待 supervisor request_approval 后 apply。

        参数：
        - agent_id：要改的 worker agent id（**不能等于当前 supervisor agent_id**，见 H15）
        - new_protocol_md：完整新 protocol（不要 diff，给完整版方便落库）
        - diff_summary：人类可读的变更摘要 ≤2000 字，给 request_approval 展示
        - trigger_summary：触发本次 propose 的原因 ≤512 字（如 "3/5 quality_gate_post block 因 unsupported_claims"）
        - expected_improvement：预期改善 ≤1000 字
        - new_soul_md：可选，同时改 soul（一般不改）

        返回 JSON：{proposal_id, status, diff_preview}
        status 可能值：pending / superseded_by_existing
        """
        from app.models.agent import Agent, AgentProtocolProposal

        if ctx.db_factory is None:
            raise ValueError("缺 db_factory")
        try:
            agent_uuid = uuid.UUID(agent_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"❌ agent_id 不是合法 UUID：{agent_id}") from exc

        # H15：supervisor 不能 propose 自己的 protocol
        current_agent_id = (ctx.extra or {}).get("agent_id")
        if current_agent_id and str(current_agent_id) == str(agent_uuid):
            raise ValueError(
                "❌ supervisor 不能调优自己的 protocol。"
                "如果你需要自己的 protocol 更新，使用 L3 mission_escalate_to_builder "
                "让 Builder Chat 来改。"
            )

        async with ctx.db_factory() as db:
            target = await db.get(Agent, agent_uuid)
            if target is None:
                raise ValueError(f"❌ agent {agent_id} 不存在")
            await _ensure_factory_initial_seeded(db, agent_uuid)

            # 校验：相同 protocol 不允许 propose（已经是这样了）
            if (new_protocol_md or "").strip() == (target.protocol_md or "").strip() and (
                not new_soul_md or new_soul_md.strip() == (target.soul_md or "").strip()
            ):
                raise ValueError("❌ 提议的 protocol 与现有完全相同，无意义")

            now = datetime.now(UTC)
            expires = now + timedelta(hours=PROPOSAL_TTL_HOURS)
            proposal = AgentProtocolProposal(
                agent_id=agent_uuid,
                proposer_agent_node_name=ctx.agent_node_name,
                proposed_soul_md=(new_soul_md or None),
                proposed_protocol_md=new_protocol_md,
                diff_summary=(diff_summary or "")[:2000],
                trigger_summary=(trigger_summary or "")[:512],
                expected_improvement=(expected_improvement or "")[:1000],
                status="pending",
                created_at=now,
                expires_at=expires,
            )
            try:
                db.add(proposal)
                await db.commit()
                await db.refresh(proposal)
            except Exception as exc:
                # H4 并发锁：unique index uq_app_one_pending_per_agent 撞了
                msg = str(exc)
                if "uq_app_one_pending_per_agent" in msg or "duplicate key" in msg.lower():
                    logger.info(
                        "📊 colony_l2_propose_superseded project=%s agent=%s",
                        ctx.mission_id, agent_id,
                    )
                    return json.dumps(
                        {
                            "status": "superseded_by_existing",
                            "message": (
                                f"agent {agent_id} 已有 pending proposal。"
                                "先 query 现有 proposal，apply 或 reject 后再 propose。"
                            ),
                        },
                        ensure_ascii=False,
                    )
                raise

        preview = _diff_preview(target.protocol_md, new_protocol_md)
        logger.info(
            "📊 colony_l2_propose project=%s agent=%s proposal=%s trigger=%r",
            ctx.mission_id, agent_id, proposal.id, trigger_summary[:80],
        )
        return json.dumps(
            {
                "proposal_id": str(proposal.id),
                "status": "pending",
                "expires_at": expires.isoformat(),
                "diff_preview": preview,
                "next_step": (
                    "调 request_approval(title='Worker 协议自调优 - <agent_name>', "
                    "message=<diff_summary + diff_preview + expected_improvement>, "
                    "options=['应用','拒绝','改写后应用']) 等用户决策。"
                    "用户通过后调 agent_protocol_apply(proposal_id, confirmed=True)。"
                ),
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_propose,
        name="agent_protocol_propose",
        description=(
            "（L2 自调优）提议修改 worker protocol。仅入 proposals 表，不改 agent。"
            "supervisor 必须紧接着调 request_approval 等用户决策，通过后再 agent_protocol_apply。"
            "**禁止**对自己 agent_id propose（H15）；同 agent 同时最多 1 条 pending（H4 并发锁）。"
        ),
    )


def agent_protocol_apply_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _apply(proposal_id: str, confirmed: bool = False) -> str:
        """把 pending proposal 应用到 agent：写 history + 调 agent_update（绕过 admin 限制）+
        抓 metrics_baseline 给 evaluate 用。

        confirmed=False → 拒绝（防止意外调用）。supervisor 在用户通过审批后才调 confirmed=True。
        """
        from app.models.agent import Agent, AgentProtocolHistory, AgentProtocolProposal

        if not confirmed:
            raise ValueError(
                "❌ apply 必须 confirmed=True。这是防止 supervisor LLM 误调的护栏，"
                "请确认用户已通过 request_approval 再调。"
            )
        if ctx.db_factory is None:
            raise ValueError("缺 db_factory")
        try:
            proposal_uuid = uuid.UUID(proposal_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"❌ proposal_id 不是合法 UUID：{proposal_id}") from exc

        async with ctx.db_factory() as db:
            proposal = await db.get(AgentProtocolProposal, proposal_uuid)
            if proposal is None:
                raise ValueError(f"❌ proposal {proposal_id} 不存在")
            if proposal.status != "pending":
                raise ValueError(
                    f"❌ proposal {proposal_id} 状态={proposal.status}，不是 pending，不能 apply"
                )
            if proposal.expires_at < datetime.now(UTC):
                proposal.status = "expired"
                await db.commit()
                raise ValueError("❌ proposal 已过期")

            # 24h apply quota
            since = datetime.now(UTC) - timedelta(hours=24)
            apply_count = (
                await db.execute(
                    select(func.count()).select_from(AgentProtocolHistory).where(
                        AgentProtocolHistory.agent_id == proposal.agent_id,
                        AgentProtocolHistory.applied_by_kind == "supervisor_self_tune",
                        AgentProtocolHistory.applied_at >= since,
                    )
                )
            ).scalar() or 0
            if apply_count >= APPLY_QUOTA_PER_AGENT_PER_24H:
                raise ValueError(
                    f"❌ 24h 内同 agent supervisor_self_tune apply 已达上限 "
                    f"{APPLY_QUOTA_PER_AGENT_PER_24H}。请走 L3 escalate_to_builder。"
                )

            target = await db.get(Agent, proposal.agent_id)
            if target is None:
                raise ValueError("❌ 目标 agent 不存在了")
            # 保证有 factory_initial baseline
            await _ensure_factory_initial_seeded(db, proposal.agent_id)
            current_version = await _current_protocol_version(db, proposal.agent_id)
            new_version = current_version + 1

            # 抓 metrics_baseline
            baseline = await _quality_gate_pass_rate(db, ctx.mission_id)
            now = datetime.now(UTC)
            history_row = AgentProtocolHistory(
                agent_id=proposal.agent_id,
                version=new_version,
                soul_md=proposal.proposed_soul_md,
                protocol_md=proposal.proposed_protocol_md,
                applied_at=now,
                applied_by_kind="supervisor_self_tune",
                applied_by_ref=str(ctx.mission_id) if ctx.mission_id else "unknown",
                trigger_summary=proposal.trigger_summary,
                rollback_of_version=None,
                metrics_baseline=baseline,
            )
            db.add(history_row)

            # 真改 agent
            if proposal.proposed_soul_md:
                target.soul_md = proposal.proposed_soul_md
            if proposal.proposed_protocol_md:
                target.protocol_md = proposal.proposed_protocol_md

            # mark proposal
            proposal.status = "applied"
            proposal.applied_at = now
            proposal.applied_history_version = new_version

            await db.commit()
            # H5 prune
            await _prune_history(db, proposal.agent_id)

            # ADR-025 · worker 修好（成功 apply 可逆 protocol 修订）→ 按 capability 唤醒所有
            # 因 worker_issue:<cap> 停工的上报方。仍坏则被唤醒方会再上报再停，不会永久 paralysis。
            if target.capability:
                try:
                    from app.services.worker_health_service import (
                        resume_waiters_for_capability,
                    )
                    await resume_waiters_for_capability(db, target.capability)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[colony_l2_apply] 唤醒 capability 等待者失败（不阻塞）cap=%s",
                        target.capability,
                    )

        logger.info(
            "📊 colony_l2_apply project=%s agent=%s proposal=%s new_version=%d baseline=%s",
            ctx.mission_id, proposal.agent_id, proposal_id, new_version, baseline,
        )
        return json.dumps(
            {
                "ok": True,
                "new_version": new_version,
                "applied_at": now.isoformat(),
                "metrics_baseline": baseline,
                "next_step": (
                    "建议 5 个 quality_gate run 之后调 agent_protocol_evaluate(agent_id, "
                    f"since_version={new_version}) 看 pass_rate 变化；regression 自动 revert。"
                ),
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_apply,
        name="agent_protocol_apply",
        description=(
            "（L2 自调优）把 pending proposal 应用到 agent；同时写 history + 抓 metrics_baseline。"
            "必须 confirmed=True；24h 内同 agent 最多 3 次 apply。"
        ),
    )


def agent_protocol_revert_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _revert(agent_id: str, to_version: int | None = None) -> str:
        """回退一个 agent 的 protocol 到指定 version；默认上一版（current-1）。
        插一行 history（applied_by_kind='supervisor_self_tune'，rollback_of_version=current）。"""
        from app.models.agent import Agent, AgentProtocolHistory

        if ctx.db_factory is None:
            raise ValueError("缺 db_factory")
        try:
            agent_uuid = uuid.UUID(agent_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"❌ agent_id 不是合法 UUID：{agent_id}") from exc

        async with ctx.db_factory() as db:
            target = await db.get(Agent, agent_uuid)
            if target is None:
                raise ValueError(f"❌ agent {agent_id} 不存在")
            current_version = await _current_protocol_version(db, agent_uuid)
            target_version = to_version if to_version is not None else max(0, current_version - 1)
            if target_version < 0:
                raise ValueError("❌ to_version < 0 非法")

            base = (
                await db.execute(
                    select(AgentProtocolHistory).where(
                        AgentProtocolHistory.agent_id == agent_uuid,
                        AgentProtocolHistory.version == target_version,
                    )
                )
            ).scalar_one_or_none()
            if base is None:
                raise ValueError(f"❌ 找不到 agent={agent_id} version={target_version} 的 history")

            new_version = current_version + 1
            now = datetime.now(UTC)
            row = AgentProtocolHistory(
                agent_id=agent_uuid,
                version=new_version,
                soul_md=base.soul_md,
                protocol_md=base.protocol_md,
                applied_at=now,
                applied_by_kind="supervisor_self_tune",
                applied_by_ref=str(ctx.mission_id) if ctx.mission_id else "auto-revert",
                trigger_summary=f"auto-revert to version {target_version}",
                rollback_of_version=target_version,
                metrics_baseline=None,
            )
            db.add(row)
            if base.soul_md is not None:
                target.soul_md = base.soul_md
            if base.protocol_md is not None:
                target.protocol_md = base.protocol_md
            await db.commit()
            await _prune_history(db, agent_uuid)

        logger.info(
            "📊 colony_l2_revert project=%s agent=%s reverted_to=%d new_version=%d",
            ctx.mission_id, agent_id, target_version, new_version,
        )
        return json.dumps(
            {
                "ok": True,
                "reverted_to_version": target_version,
                "new_version": new_version,
                "applied_at": now.isoformat(),
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_revert,
        name="agent_protocol_revert",
        description=(
            "（L2 自调优）回退 agent protocol 到指定 history version；默认上一版。"
            "插一行 history（rollback_of_version 非空）作为审计痕。"
        ),
    )


def agent_protocol_evaluate_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _evaluate(agent_id: str, since_version: int) -> str:
        """看 since_version 以来的 quality_gate pass-rate 与 metrics_baseline 比较。
        返回 {pass_rate_delta, samples, recommendation: keep|revert}。
        pass_rate_delta < -0.1 且 samples ≥ 5 → recommendation='revert'。
        """
        from app.models.agent import AgentProtocolHistory

        if ctx.db_factory is None:
            raise ValueError("缺 db_factory")
        try:
            agent_uuid = uuid.UUID(agent_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"❌ agent_id 不是合法 UUID：{agent_id}") from exc

        async with ctx.db_factory() as db:
            base_row = (
                await db.execute(
                    select(AgentProtocolHistory).where(
                        AgentProtocolHistory.agent_id == agent_uuid,
                        AgentProtocolHistory.version == since_version,
                    )
                )
            ).scalar_one_or_none()
            if base_row is None:
                raise ValueError(f"❌ agent={agent_id} version={since_version} 不存在")
            baseline = base_row.metrics_baseline or {}
            base_pass_rate = float(baseline.get("pass_rate") or 0.0)
            base_samples = int(baseline.get("samples") or 0)

            current = await _quality_gate_pass_rate(db, ctx.mission_id)

            # ADR-015 · 跨调用方兼容门：以 apply 时刻为界，逐 (super, action) 比成功率。
            # 任一在用调用方明显退化 → 强制 revert（worker 全局共享，不能「一边好一边坏」）。
            cross_caller: dict | None = None
            try:
                # AgentProtocolHistory 没有 created_at，只有 applied_at（修：之前取 .created_at
                # 抛 AttributeError 被吞 → ADR-015 跨调用方兼容门形同虚设）
                applied_at = base_row.applied_at
                before = await _fetch_caller_stats(db, agent_uuid, until=applied_at)
                after = await _fetch_caller_stats(db, agent_uuid, since=applied_at)
                from app.domain.optimization.compat_gate import check_cross_caller_compat
                verdict = check_cross_caller_compat(before, after)
                cross_caller = {
                    "compatible": verdict.compatible,
                    "regressed_callers": verdict.regressed_callers,
                    "reason": verdict.reason,
                }
            except Exception:
                logger.exception("[l2_evaluate] 跨调用方兼容门检查失败（不阻塞）")

        delta = current["pass_rate"] - base_pass_rate
        recommendation = "keep"
        if current["samples"] >= 5 and delta < -0.1:
            recommendation = "revert"
        # 跨调用方退化优先级最高：哪怕本项目 pass-rate 守住，破坏别的 super 也必须回滚
        if cross_caller and not cross_caller["compatible"]:
            recommendation = "revert"
        logger.info(
            "📊 colony_l2_evaluate project=%s agent=%s since=%d delta=%.3f samples=%d rec=%s",
            ctx.mission_id, agent_id, since_version, delta, current["samples"], recommendation,
        )
        return json.dumps(
            {
                "agent_id": agent_id,
                "since_version": since_version,
                "baseline": {"pass_rate": base_pass_rate, "samples": base_samples},
                "current": current,
                "pass_rate_delta": round(delta, 3),
                "samples": current["samples"],
                "cross_caller_compat": cross_caller,
                "recommendation": recommendation,
                "note": (
                    "samples < 5 时永不返回 revert（统计不足）；建议 supervisor 等更多 run 再 evaluate。"
                    if current["samples"] < 5 else "satisfies cap"
                ),
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_evaluate,
        name="agent_protocol_evaluate",
        description=(
            "（L2 自调优）评估某次 apply 之后的效果：比较 quality_gate pass-rate 与"
            " metrics_baseline；pass_rate_delta < -0.1 且 samples ≥ 5 → 建议 revert。"
            " 另含**跨调用方兼容门**（ADR-015）：以 apply 时刻为界逐 (super,action) 比成功率，"
            " 任一在用调用方明显退化即强制 revert（worker 全局共享，不能一边好一边坏）。"
        ),
    )
