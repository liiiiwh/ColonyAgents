"""L3 · 项目 → Builder 升级通道 skills。

- `mission_escalate_to_builder`：supervisor 发升级信封；带 quota / fingerprint dedup
- `mission_escalation_resolve`：Builder Chat 处理完后闭环（resolved_by, resolution_summary）
- `mission_escalation_dismiss`：supervisor / admin 主动取消
- `mission_escalation_list`：读自己项目的最近 N 条 escalation 状态

H6 死信兜底（scheduler 周期 job）：见 scheduler_service 注册的 nightly job。
H7 项目自动降速：见 _maybe_auto_pause_schedules（在 escalate 内调）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from langchain_core.tools import StructuredTool
from sqlalchemy import and_, func, select

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


SUMMARY_MAX = 280
EVIDENCE_MAX_BYTES = 4000
PROPOSED_CHANGE_MAX = 2000
DAILY_QUOTA_DEFAULT = 3
AUTO_PAUSE_UNRESOLVED_THRESHOLD = 3  # H7：unresolved ≥ 3 → 自动暂停 schedule


def _fingerprint(category: str, summary: str, worker_id: str | None) -> str:
    """归一化 summary 后做 sha256；忽略数字 / UUID / 时间戳让相似根因合并。"""
    import re
    norm = summary or ""
    norm = re.sub(r"\d+", "N", norm)  # 数字归一
    norm = re.sub(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", "U", norm)
    norm = re.sub(r"\s+", " ", norm).strip().lower()
    seed = f"{category}|{norm}|{worker_id or ''}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:64]


def _get_quota(project, today_utc) -> int:
    wf = (getattr(project, "workflow_config", None) or {})
    q = wf.get("escalation_quota_remaining")
    last_reset = wf.get("escalation_quota_reset_date")
    if last_reset != today_utc:
        return DAILY_QUOTA_DEFAULT
    return int(q if q is not None else DAILY_QUOTA_DEFAULT)


def _consume_quota(project, today_utc: str) -> None:
    wf = dict(getattr(project, "workflow_config", None) or {})
    last_reset = wf.get("escalation_quota_reset_date")
    if last_reset != today_utc:
        wf["escalation_quota_remaining"] = DAILY_QUOTA_DEFAULT
        wf["escalation_quota_reset_date"] = today_utc
    wf["escalation_quota_remaining"] = max(0, int(wf.get("escalation_quota_remaining", DAILY_QUOTA_DEFAULT)) - 1)
    project.workflow_config = wf


async def _count_unresolved(db, mission_id: uuid.UUID) -> int:
    """ADR-028 D3 · Builder 视角：数「投递给本 builder mission 的未处理升级」。

    定义 = 由本 builder mission 产出的 super（agent.built_by_mission_id == mission_id）
    所对应 mission 上 status∈(pending,delivered) 的 escalation 总数。

    不再按 escalation.mission_id == mission_id 查（那是 super 自己发的归属，Builder 看不到）。
    """
    from app.models.agent import Agent
    from app.models.mission import Mission, MissionEscalation
    c = (
        await db.execute(
            select(func.count())
            .select_from(MissionEscalation)
            .join(Mission, MissionEscalation.mission_id == Mission.id)
            .join(Agent, Mission.supervisor_agent_id == Agent.id)
            .where(
                Agent.built_by_mission_id == mission_id,
                MissionEscalation.status.in_(("pending", "delivered")),
            )
        )
    ).scalar()
    return int(c or 0)


async def _maybe_auto_pause_schedules(db, mission_id: uuid.UUID) -> bool:
    """ADR-028 D4 · H4 · 仅监控，**不再翻转 schedule.enabled**（退役有损翻转）。

    调度器原则：schedule.enabled 永不被代码自动改写——「停/开调度」由 fire_one 按 mission
    lifecycle 决定 run/skip 实现（逻辑级门控，保用户配置 + 崩溃安全）。unresolved 堆积时
    super 自身会进 paused_waiting_capability → fire_one 自然 skip，无需动 schedule 配置。

    保留监控日志（unresolved≥阈值时告警）；恒返回 False（不再触发有损暂停）。"""
    unresolved = await _count_unresolved(db, mission_id)
    if unresolved >= AUTO_PAUSE_UNRESOLVED_THRESHOLD:
        logger.warning(
            "📊 colony_l3_unresolved_high project=%s unresolved=%d（仅监控，不动 schedule.enabled）",
            mission_id, unresolved,
        )
    return False


def mission_escalate_to_builder_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _escalate(
        category: str,
        severity: str,
        summary: str,
        evidence_json: str = "{}",
        proposed_change: str = "",
        worker_agent_id: str = "",
    ) -> str:
        """L3：worker-project supervisor 向 origin Builder Chat 发升级信封。

        参数：
        - category：'structural' / 'resource' / 'strategy_pivot' / 'stuck'
        - severity：'info' / 'warn' / 'critical'
        - summary：≤280 字（推文级），用户在 wechat 推送里直接看到
        - evidence_json：JSON 字符串，≤4KB（包含 sample_verdicts / agent_id 等结构化证据）
        - proposed_change：≤2000 字描述「我建议 Builder 做什么改动」
        - worker_agent_id：可选，相关的 worker agent_id（影响 fingerprint 去重）

        返回：{ok, escalation_id, status: queued|deduped|quota_exhausted|dismissed}
        - queued：新行已写入；async dispatcher 投递到 Builder session
        - deduped：同 fingerprint 同天已有，本次不再发
        - quota_exhausted：3/天/项目用完；不发新行 + 触发 H7 auto-pause（如未达）
        """
        from app.models.mission import Mission, MissionEscalation
        from app.services.escalation_dispatcher import fire_escalation

        if ctx.db_factory is None or ctx.mission_id is None:
            raise ValueError("缺 db_factory / mission_id 上下文")
        if category not in ("structural", "resource", "strategy_pivot", "stuck", "worker_health"):
            raise ValueError(f"❌ category 不合法：{category}")
        if severity not in ("info", "warn", "critical"):
            raise ValueError(f"❌ severity 不合法：{severity}")
        summary = (summary or "").strip()
        if not summary:
            raise ValueError("❌ summary 不能为空")
        if len(summary) > SUMMARY_MAX:
            raise ValueError(f"❌ summary 必须 ≤{SUMMARY_MAX} 字符，当前 {len(summary)}")
        proposed_change = (proposed_change or "")[:PROPOSED_CHANGE_MAX]

        # evidence_json 解析 + cap
        try:
            ev = json.loads(evidence_json) if isinstance(evidence_json, str) else dict(evidence_json or {})
            if not isinstance(ev, dict):
                ev = {"_raw": str(ev)[:2000]}
        except json.JSONDecodeError:
            ev = {"_raw": str(evidence_json)[:2000]}
        ev_blob = json.dumps(ev, ensure_ascii=False)
        if len(ev_blob) > EVIDENCE_MAX_BYTES:
            # 砍掉过大字段
            ev = {"_truncated": True, "_summary": ev_blob[:EVIDENCE_MAX_BYTES - 200] + "..."}

        today_utc = datetime.now(UTC).date().isoformat()
        fp = _fingerprint(category, summary, worker_agent_id or None)

        async with ctx.db_factory() as db:
            project = await db.get(Mission, ctx.mission_id)
            if project is None:
                raise ValueError("❌ project 不存在")

            # 检查 quota
            quota = _get_quota(project, today_utc)
            if quota <= 0:
                # H7 触发条件之一
                await _maybe_auto_pause_schedules(db, ctx.mission_id)
                logger.warning(
                    "📊 colony_l3_quota_exhausted project=%s category=%s",
                    ctx.mission_id, category,
                )
                return json.dumps(
                    {"ok": False, "status": "quota_exhausted",
                     "message": "3/day quota used; H7 auto-pause may have triggered."},
                    ensure_ascii=False,
                )

            row = MissionEscalation(
                mission_id=ctx.mission_id,
                created_at=datetime.now(UTC),
                category=category,
                severity=severity,
                summary=summary,
                evidence_json=ev,
                proposed_change=proposed_change,
                fingerprint=fp,
                status="pending",
            )
            try:
                db.add(row)
                await db.commit()
                await db.refresh(row)
            except Exception as exc:
                msg = str(exc)
                if "uq_pe_project_fp_day" in msg or "duplicate key" in msg.lower():
                    logger.info(
                        "📊 colony_l3_deduped project=%s fp=%s",
                        ctx.mission_id, fp[:12],
                    )
                    return json.dumps(
                        {"ok": True, "status": "deduped", "fingerprint": fp,
                         "message": "同 fingerprint 今天已升级过，dedup"},
                        ensure_ascii=False,
                    )
                raise

            # 消费 quota
            _consume_quota(project, today_utc)
            await db.commit()
            # H7 检查
            await _maybe_auto_pause_schedules(db, ctx.mission_id)

        # 异步投递
        fire_escalation(row.id)

        logger.info(
            "📊 colony_l3_queued project=%s escalation=%s category=%s severity=%s",
            ctx.mission_id, row.id, category, severity,
        )
        return json.dumps(
            {
                "ok": True,
                "escalation_id": str(row.id),
                "status": "queued",
                "fingerprint": fp,
                "remaining_quota_today": _get_quota(project, today_utc),
                "note": (
                    "已异步投递到 origin Builder Chat session。"
                    "不要再就同一 fingerprint 写第二条 —— 同根因当天 dedup。"
                    "等 Builder 通过 mission_escalation_resolve 闭环；不要循环重试。"
                ),
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_escalate,
        name="mission_escalate_to_builder",
        description=(
            "（L3）worker-project supervisor 向 origin Builder Chat session 发升级信封。"
            "用于：缺工具 / 需要新 worker / 策略调整 / 自调优撞顶后兜底。"
            "size cap：summary≤280 / evidence≤4KB / proposed_change≤2000。"
            "**3/day/项目 quota**；同 fingerprint 同天 dedup；超 3 条 unresolved 自动暂停 schedule（H7）。"
        ),
    )


def mission_escalation_resolve_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _resolve(
        escalation_id: str,
        resolution_summary: str,
    ) -> str:
        """（Builder Chat 专用）处理完一条 escalation 后闭环。
        resolution_summary 写一下你做了什么改动（例：「为 publish 节点新增 fact_checker worker」）。
        """
        from app.models.mission import MissionEscalation
        if ctx.db_factory is None:
            raise ValueError("缺 db_factory")
        try:
            eid = uuid.UUID(escalation_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"❌ escalation_id 不是 UUID：{escalation_id}") from exc
        if not resolution_summary.strip():
            raise ValueError("❌ resolution_summary 不能为空")

        async with ctx.db_factory() as db:
            row = await db.get(MissionEscalation, eid)
            if row is None:
                raise ValueError(f"❌ escalation {escalation_id} 不存在")
            row.status = "acted"
            row.resolution_summary = resolution_summary.strip()[:2000]
            row.resolved_at = datetime.now(UTC)
            row.resolved_by = str(ctx.mission_id) if ctx.mission_id else "unknown"
            await db.commit()
        logger.info(
            "📊 colony_l3_resolved escalation=%s by_session=%s",
            escalation_id, ctx.mission_id,
        )
        return json.dumps({"ok": True, "escalation_id": escalation_id, "status": "acted"}, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_resolve,
        name="mission_escalation_resolve",
        description=(
            "（L3 Builder Chat 专用）处理完一条 project_escalation 后闭环。"
            "Builder 完成 EDIT 模式调整 / 拒绝 / 沟通后必调一次，让 supervisor 知道问题已处理。"
        ),
    )


def mission_escalation_dismiss_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _dismiss(escalation_id: str, reason: str = "") -> str:
        """主动取消一条 escalation（supervisor 自己改口 / admin 干预）。"""
        from app.models.mission import MissionEscalation
        if ctx.db_factory is None:
            raise ValueError("缺 db_factory")
        try:
            eid = uuid.UUID(escalation_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"❌ escalation_id 不是 UUID：{escalation_id}") from exc
        async with ctx.db_factory() as db:
            row = await db.get(MissionEscalation, eid)
            if row is None:
                raise ValueError(f"❌ escalation {escalation_id} 不存在")
            row.status = "dismissed"
            row.resolution_summary = (reason or "dismissed by supervisor")[:500]
            row.resolved_at = datetime.now(UTC)
            row.resolved_by = str(ctx.mission_id) if ctx.mission_id else "unknown"
            await db.commit()
        return json.dumps({"ok": True, "escalation_id": escalation_id, "status": "dismissed"}, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_dismiss,
        name="mission_escalation_dismiss",
        description="（L3）取消一条 escalation（自己 / admin）。",
    )


def mission_escalation_list_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _list(limit: int = 10, only_open: bool = True) -> str:
        """ADR-028 D3 · Builder 视角：列「投递给本 builder mission 的升级」。

        = 由本 builder mission 产出的 super（agent.built_by_mission_id == 本 mission）
        所对应 mission 上的 escalation；而非本 builder mission 自己发的升级。
        """
        from app.models.agent import Agent
        from app.models.mission import Mission, MissionEscalation
        if ctx.db_factory is None or ctx.mission_id is None:
            raise ValueError("缺上下文")
        async with ctx.db_factory() as db:
            stmt = (
                select(MissionEscalation)
                .join(Mission, MissionEscalation.mission_id == Mission.id)
                .join(Agent, Mission.supervisor_agent_id == Agent.id)
                .where(Agent.built_by_mission_id == ctx.mission_id)
            )
            if only_open:
                stmt = stmt.where(MissionEscalation.status.in_(("pending", "delivered")))
            stmt = stmt.order_by(MissionEscalation.created_at.desc()).limit(max(1, min(limit, 50)))
            rows = (await db.execute(stmt)).scalars().all()
        return json.dumps(
            [
                {
                    "id": str(r.id),
                    "created_at": r.created_at.isoformat(),
                    "category": r.category,
                    "severity": r.severity,
                    "summary": r.summary,
                    "status": r.status,
                    "fingerprint": r.fingerprint,
                }
                for r in rows
            ],
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_list,
        name="mission_escalation_list",
        description="（L3）列自己项目最近 N 条 escalation 状态，supervisor 决策时参考用。",
    )
