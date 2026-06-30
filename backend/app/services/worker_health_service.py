"""平台 Worker 健康自检自迭代服务 · ADR-015。

系统级 WorkerHealthSession（scope='system'，挂 Builder Mission，不可删除）。
调度 tick 两段式：
  1. 确定性体检（纯代码）：从 worker_invocation_log 聚合 → health_scan.scan_worker_health
     筛候选。无候选 → 只记一行「全部健康」，不唤起 LLM（省 token）。
  2. LLM 决策：有候选 → 把体检报告写进会话 + 跑一轮 Builder Super LLM turn（带 L2 四件套），
     由 LLM 诊断 + 起草 protocol 修订。L2 apply 路径已接跨调用方兼容门（compat_gate）。

设计：所有 DB 失败/ LLM 失败都 best-effort 不抛（调度 job 不能因单次体检崩）。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import text as _sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.domain.optimization.health_scan import WorkerHealthInput, scan_worker_health
from app.models.mission import Mission

logger = logging.getLogger(__name__)


async def resume_waiters_for_capability(db: AsyncSession, capability: str) -> int:
    """ADR-025 · worker 修好后按 capability 唤醒所有停工等待的上报方 mission。

    上报方 report_worker_issue(pause=True) 停成 paused_waiting_capability、
    reason=`worker_issue:<cap>: ...`。worker-opt 成功 apply 修复该 capability 后调本函数，
    把所有这些等待者 RESUME→running 并触发续跑 tick。返回唤醒数。

    确定性、按 capability（非按上报方身份）→ 天然支持多个 super 等同一 worker；不依赖人工/Builder。
    仍坏则被唤醒的 super 会再次上报再停，不会永久 paralysis。"""
    if not capability:
        return 0
    prefix = f"worker_issue:{capability}:"  # 带尾冒号防 data 前缀撞 data_fetcher
    rows = (await db.execute(
        select(Mission).where(
            Mission.lifecycle_status == "paused_waiting_capability",
            Mission.paused_reason.like(f"{prefix}%"),
        )
    )).scalars().all()
    woken = 0
    for proj in rows:
        try:
            from app.domain.lifecycle import LifecycleAction
            from app.domain.lifecycle_service import LifecycleService

            await LifecycleService(db).transition(
                proj.id, LifecycleAction.RESUME, force=True,
                reason=f"worker_fixed:{capability}",
            )
            woken += 1
        except Exception:  # noqa: BLE001
            logger.exception("[worker_opt] 唤醒等待者失败 mission=%s cap=%s", proj.id, capability)
            continue
        # best-effort 触发续跑 tick（idle 时立即开跑；正跑则排队）
        try:
            from app.api.super_conversation import _trigger_tick_async
            from app.core.bg_tasks import spawn
            spawn(_trigger_tick_async(proj.id), name=f"worker-fixed-resume-{proj.id}")
        except Exception:  # noqa: BLE001
            logger.exception("[worker_opt] 唤醒后触发 tick 失败（不阻塞）mission=%s", proj.id)
    if woken:
        logger.info("[worker_opt] capability=%s 修好，唤醒 %d 个等待者", capability, woken)
    return woken


async def _ensure_worker_opt_host(db: AsyncSession) -> Mission | None:
    """ADR-018 mission-only · 自检宿主 = Colony Worker Optimization mission（无 session/branch 行）。

    返回 mission。worker-opt super / admin 未就绪 → None。"""
    from app.services.worker_optimization_service import ensure_worker_optimization_super

    seeded = await ensure_worker_optimization_super(db)
    if seeded is None:
        return None
    _agent, mission = seeded
    return mission


async def _fetch_health_inputs(db: AsyncSession, window_days: int = 7) -> list[WorkerHealthInput]:
    """从 worker_invocation_log 聚合每个 worker 的健康指标（含 top 重复错误）。"""
    rows = (await db.execute(_sql_text("""
        WITH agg AS (
            SELECT w.worker_agent_id AS wid,
                   COUNT(*) AS total,
                   SUM(CASE WHEN w.status='completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN w.status='failed' THEN 1 ELSE 0 END) AS failed
              FROM worker_invocation_log w
             WHERE w.started_at >= now() - make_interval(days => :wd)
             GROUP BY w.worker_agent_id
        ),
        toperr AS (
            SELECT DISTINCT ON (worker_agent_id)
                   worker_agent_id AS wid,
                   SUBSTRING(error_msg, 1, 200) AS msg,
                   COUNT(*) AS cnt
              FROM worker_invocation_log
             WHERE status='failed' AND error_msg IS NOT NULL
               AND started_at >= now() - make_interval(days => :wd)
             GROUP BY worker_agent_id, SUBSTRING(error_msg, 1, 200)
             ORDER BY worker_agent_id, cnt DESC
        )
        SELECT a.wid, ag.name, ag.capability,
               a.total, a.completed, a.failed,
               COALESCE(t.cnt, 0) AS top_err_cnt, t.msg AS top_err_msg
          FROM agg a
          JOIN agents ag ON ag.id = a.wid
          LEFT JOIN toperr t ON t.wid = a.wid
         WHERE ag.kind = 'worker'
    """), {"wd": window_days})).mappings().all()
    return [
        WorkerHealthInput(
            worker_id=str(r["wid"]), name=r["name"], capability=r["capability"],
            total=int(r["total"]), completed=int(r["completed"]), failed=int(r["failed"]),
            top_repeated_error_cnt=int(r["top_err_cnt"]), top_error_msg=r["top_err_msg"],
        )
        for r in rows
    ]


def _candidate_report(c) -> str:
    """单个退化候选 → work-order mission 的首条诊断报告。"""
    return (
        f"[🩺 worker 退化体检 · capability={c.capability}]\n"
        f"worker={c.name}（id={c.worker_id}）成功率={c.success_rate:.0%} 样本={c.total}\n"
        f"判定：{c.reason}" + (f"\n高频错误：{c.top_error_msg}" if c.top_error_msg else "") + "\n\n"
        "按保守门控协议处理：可逆则 agent_protocol_propose→apply（过跨调用方兼容门），归因不清/样本不足"
        "则观察记录，不可逆动作 force_human=True 升级真人。完成调 optimization_done；未完成调 "
        "optimization_continue 续跑。"
    )


async def dispatch_health_candidates(
    db: AsyncSession, *, super_agent_id, created_by, candidates: list
) -> list[Mission]:
    """ADR-025 D1 · 派发器核心：每个退化候选 → spawn/attach 一个 work-order mission（同 worker
    去重、跨 worker 并行）。返回涉及的 mission 列表（不在此启动 daemon——见 _activate_work_order）。"""
    from app.services.worker_optimization_service import spawn_or_attach_work_order

    missions: list[Mission] = []
    for c in candidates:
        cap = c.capability or "unknown"
        m, _created = await spawn_or_attach_work_order(
            db, super_agent_id=super_agent_id, created_by=created_by,
            capability=cap, worker_agent_id=str(c.worker_id), report=_candidate_report(c),
        )
        missions.append(m)
    return missions


async def run_health_tick(db: AsyncSession, window_days: int = 7) -> dict:
    """调度入口。返回 {ok, candidates, acted}。全程 best-effort。"""
    ensured = await _ensure_worker_opt_host(db)
    if ensured is None:
        return {"ok": False, "reason": "Worker Optimization super 未就绪"}
    proj = ensured

    try:
        inputs = await _fetch_health_inputs(db, window_days)
    except Exception:
        logger.exception("[worker_health] 体检聚合失败")
        return {"ok": False, "reason": "体检聚合失败"}

    candidates = scan_worker_health(inputs)

    from app.services import messaging_service

    if not candidates:
        await messaging_service.append_message(
            db, proj.id, "main", role="agent_log",
            content=f"[健康自检] 扫描 {len(inputs)} 个 worker，全部健康，无需迭代。",
            meta={"type": "worker_health_scan", "candidates": 0, "scanned": len(inputs)},
        )
        return {"ok": True, "candidates": 0, "acted": False}

    # ADR-025 D1 · 派发器：体检报告记到 dispatcher mission 留痕；然后给每个退化 worker
    # fan-out 一个独立 work-order mission（同 worker 去重、跨 worker 并行）并启动它跑到完成。
    await messaging_service.append_message(
        db, proj.id, "main", role="agent_log",
        content=f"[健康自检] 发现 {len(candidates)} 个退化 worker，已派发 work-order。",
        meta={"type": "worker_health_report", "candidates": len(candidates),
              "worker_ids": [c.worker_id for c in candidates]},
    )
    missions = await dispatch_health_candidates(
        db, super_agent_id=proj.supervisor_agent_id, created_by=proj.created_by,
        candidates=candidates,
    )
    from app.services.worker_optimization_service import activate_work_order
    for m in missions:
        await activate_work_order(db, m.id, proj.created_by)
    return {"ok": True, "candidates": len(candidates), "dispatched": len(missions)}


async def submit_worker_issue(
    db: AsyncSession,
    *,
    capability: str,
    evidence: str,
    severity: str = "warn",
    worker_agent_id: str = "",
) -> bool:
    """ADR-018 D2 输入②：任一 super 上报"某 worker 坏了" → 落到 Colony Worker Optimization
    mission 作优化输入 + 尽力跑一轮该 super 处理。返回是否成功投递（worker-opt 未就绪 → False）。

    ADR-025 · spawn/attach 一个 work-order mission（同 worker 去重）并启动它跑到完成。
    返回是否成功投递（worker-opt 未就绪 → False）。"""
    ensured = await _ensure_worker_opt_host(db)
    if ensured is None:
        return False
    proj = ensured

    report = (
        "[🛠 worker 优化上报 · 来自某 super 的运行 mission]\n"
        f"worker capability={capability}（id={worker_agent_id or '-'}, severity={severity}）\n"
        f"证据：{evidence[:3000]}\n\n"
        "按你的保守门控协议处理：可逆则 propose+apply 过跨调用方兼容门，归因不清/样本不足则观察记录，"
        "不可逆动作 force_human=True 升级真人。完成调 optimization_done；未完成调 optimization_continue。"
    )
    from app.services.worker_optimization_service import (
        activate_work_order,
        spawn_or_attach_work_order,
    )
    m, _created = await spawn_or_attach_work_order(
        db, super_agent_id=proj.supervisor_agent_id, created_by=proj.created_by,
        capability=capability, worker_agent_id=worker_agent_id, report=report,
    )
    await activate_work_order(db, m.id, proj.created_by)
    return True


async def record_worker_issue(
    db: AsyncSession,
    *,
    capability: str,
    evidence: str,
    severity: str = "warn",
    worker_agent_id: str = "",
    source: str = "auto",
) -> bool:
    """ADR-025 · 高频自动降级信号（如 MCP 调用失败）：spawn/attach work-order 并挂兜底调度，
    但**不 kickoff 立即跑**——避免每个高频事件都唤起 LLM。dedup 保证同 capability 只一个 work-order，
    它由兜底调度/下次 submit 驱动。返回是否成功记录。"""
    ensured = await _ensure_worker_opt_host(db)
    if ensured is None:
        return False
    proj = ensured

    report = (
        f"[🛠 worker 自动降级信号 · source={source}]\n"
        f"capability={capability}（id={worker_agent_id or '-'}, severity={severity}）\n"
        f"证据：{evidence[:2000]}"
    )
    from app.services.worker_optimization_service import (
        _ensure_backstop_schedule,
        spawn_or_attach_work_order,
    )
    m, _created = await spawn_or_attach_work_order(
        db, super_agent_id=proj.supervisor_agent_id, created_by=proj.created_by,
        capability=capability, worker_agent_id=worker_agent_id, report=report,
    )
    # 不 kickoff（高频省 token），仅挂兜底调度让它最终被处理
    await _ensure_backstop_schedule(db, m.id, proj.created_by)
    return True
