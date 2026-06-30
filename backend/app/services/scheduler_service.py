"""M2：项目调度（APScheduler in-process）。

设计：
- DB 表 `mission_schedule` 是真相；APScheduler 内存 jobstore 在启动时从 DB rehydrate。
- 任何 schedule 增 / 改 / 删后调 `reschedule_one(...)`（或 `delete_one(...)`）即时同步内存 scheduler。
- cron / interval 由 APScheduler 自动触发；event 不挂 APScheduler，靠 webhook 手动触发。
- 触发执行：fire_one() 拿到 schedule + project，调 `mission_daemon.run_once(mission_id, payload)`，
  写回 last_fired_at / next_fire_at / fire_count / last_error。
- Scheduler 实例是模块全局 `_scheduler`；通过 `start()` / `stop()` 控制 lifespan。
"""

from __future__ import annotations

import logging
import re
import uuid
from contextlib import suppress
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session as _db_session
from app.models.mission import MissionSchedule

logger = logging.getLogger(__name__)


def _open_session() -> AsyncSession:
    return _db_session.AsyncSessionLocal()


# ─────────────────────────── 全局 scheduler ───────────────────────────
_scheduler: AsyncIOScheduler | None = None


def _make_job_id(schedule_id: uuid.UUID) -> str:
    return f"sched-{schedule_id}"


def _expr_to_trigger(kind: str, expr: str):
    if kind == "cron":
        return CronTrigger.from_crontab(expr)
    if kind == "interval":
        m = re.fullmatch(r"(\d+)([smhd])", expr)
        if not m:
            raise ValueError(f"interval expr 非法：{expr!r}")
        n = int(m.group(1))
        unit = m.group(2)
        kwargs = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[unit]
        return IntervalTrigger(**{kwargs: n})
    # event 不挂 APScheduler
    raise ValueError(f"event kind 不应注册到 APScheduler")


async def _job_fn(schedule_id_str: str) -> None:
    """APScheduler job 入口。"""
    sid = uuid.UUID(schedule_id_str)
    await fire_one(sid)


def _render_payload_placeholders(
    payload: dict, *, now: datetime | None = None, slug: str | None = None
) -> dict:
    """对 payload 中的字符串值做占位符替换（白名单纯字符串替换，不 eval）。

    支持：
    - `{date}` → '2026-05-22'（按 server 本地时区取 .date()）
    - `{hour}` → '23'（2 位补零）
    - `{weekday}` → 'mon' / 'tue' / ...
    - `{datetime}` → '2026-05-22T15:30:00'（秒级，无时区）
    - `{slug}` → project.slug（如提供）

    用途：cron `0 10 * * *` 每天触发时 `task_group='{slug}-day-{date}'` 自动滚动。
    递归处理 dict / list；非字符串值原样保留。
    """
    if not isinstance(payload, dict) or not payload:
        return payload
    n = now or datetime.now()
    repl = {
        "{date}": n.date().isoformat(),
        "{hour}": f"{n.hour:02d}",
        "{weekday}": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][n.weekday()],
        "{datetime}": n.replace(microsecond=0).isoformat(),
    }
    if slug:
        repl["{slug}"] = slug

    def _walk(v):
        if isinstance(v, str):
            out = v
            for k, rv in repl.items():
                if k in out:
                    out = out.replace(k, rv)
            return out
        if isinstance(v, dict):
            return {kk: _walk(vv) for kk, vv in v.items()}
        if isinstance(v, list):
            return [_walk(x) for x in v]
        return v

    return _walk(payload)


async def fire_one(schedule_id: uuid.UUID, *, override_payload: dict | None = None) -> dict:
    """触发一次 schedule。返回 run_once 的结果 dict。

    被 APScheduler 调度的 cron / interval、以及 webhook event 都走这里。
    """
    from app.services import mission_daemon  # 延迟 import 避免循环

    async with _open_session() as db:
        sched = await db.get(MissionSchedule, schedule_id)
        if sched is None:
            logger.warning("[scheduler] fire_one: schedule %s 不存在，已撤销", schedule_id)
            with suppress(Exception):
                if _scheduler is not None:
                    _scheduler.remove_job(_make_job_id(schedule_id))
            return {"ok": False, "error": "schedule 不存在"}
        if not sched.enabled:
            logger.info("[scheduler] fire_one: schedule %s 已 disabled, skip", schedule_id)
            return {"ok": False, "error": "disabled"}

        raw_payload = dict(override_payload or sched.payload_template or {})
        # M2：在 fire 时渲染占位符（不缓存），保证 cron 每次拿到当天日期
        # 顺便注入 project.slug 供 task_group 模板使用
        proj_slug: str | None = None
        with suppress(Exception):
            from app.models.mission import Mission
            _p = await db.get(Mission, sched.mission_id)
            if _p:
                proj_slug = _p.slug
        # ADR-028 D4 · 调度器逻辑级门控：按 mission lifecycle 决定 run/skip，**绝不改 schedule.enabled**
        # （保用户配置 + 崩溃安全）。paused_for_human / stopped / error → skip（观感=停调度）；
        # paused_idle / running → run（paused_idle 到点拉新一轮）。
        from app.domain.tick_policy import should_run_on_schedule
        from app.models.mission import Mission as _Mission
        _proj = await db.get(_Mission, sched.mission_id)
        _ls = (_proj.lifecycle_status if _proj else "") or ""
        if _proj is not None and not should_run_on_schedule(lifecycle_status=_ls):
            logger.info(
                "[scheduler] fire_one: schedule %s mission lifecycle=%s → skip（不动 enabled）",
                schedule_id, _ls,
            )
            return {"ok": True, "skipped": "lifecycle_gate", "lifecycle_status": _ls}

        payload = _render_payload_placeholders(raw_payload, slug=proj_slug)
        # 给 daemon 新分支带上触发摘要，UI 历史回溯能看出每次 run 是哪个 schedule 触发的
        payload.setdefault("trigger", f"{sched.kind} {sched.expr}")
        payload["schedule_expr"] = sched.expr
        # 注入 schedule_id 给 daemon —— fallback task_group 用 'sched-<id>-<date>'
        payload["schedule_id"] = str(schedule_id)
        result: dict
        try:
            result = await mission_daemon.run_once(db, sched.mission_id, payload)
            sched.last_fired_at = datetime.now(UTC)
            sched.fire_count += 1
            sched.last_error = None
            # next_fire_at 由 APScheduler 自己算（事件后会自动更新 job）；
            # 这里只更新 _job_meta，可选回填。
            if _scheduler is not None and sched.kind in ("cron", "interval"):
                with suppress(Exception):
                    j = _scheduler.get_job(_make_job_id(schedule_id))
                    if j is not None:
                        sched.next_fire_at = j.next_run_time
        except Exception as exc:  # noqa: BLE001
            logger.exception("[scheduler] fire_one: schedule %s 执行失败", schedule_id)
            sched.last_error = str(exc)[:500]
            result = {"ok": False, "error": str(exc)}
        await db.commit()
        return result


def reschedule_one(schedule: MissionSchedule) -> None:
    """根据 MissionSchedule 当前状态注册 / 重注册 / 删除 APScheduler job。

    同步调用（无 await），直接操作 APScheduler 内存表。
    """
    if _scheduler is None:
        return
    job_id = _make_job_id(schedule.id)
    # event 类 / disabled / project deleted 都删除 job
    if schedule.kind == "event" or not schedule.enabled:
        with suppress(Exception):
            _scheduler.remove_job(job_id)
        return
    try:
        trigger = _expr_to_trigger(schedule.kind, schedule.expr)
    except Exception:
        logger.exception("[scheduler] expr 非法，跳过 %s", schedule.id)
        with suppress(Exception):
            _scheduler.remove_job(job_id)
        return
    # add_job(replace_existing=True) = upsert
    _scheduler.add_job(
        _job_fn,
        trigger=trigger,
        id=job_id,
        args=[str(schedule.id)],
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )


def delete_one(schedule_id: uuid.UUID) -> None:
    if _scheduler is None:
        return
    with suppress(Exception):
        _scheduler.remove_job(_make_job_id(schedule_id))


async def rehydrate_from_db() -> int:
    """启动期把所有 enabled cron/interval schedule 注册到内存 scheduler。
    event 类不注册。返回注册数量。
    """
    if _scheduler is None:
        return 0
    n = 0
    async with _open_session() as db:
        rows = await db.execute(
            select(MissionSchedule).where(
                MissionSchedule.enabled.is_(True),
                MissionSchedule.kind.in_(("cron", "interval")),
            )
        )
        for sched in rows.scalars().all():
            try:
                reschedule_one(sched)
                n += 1
            except Exception:
                logger.exception("[scheduler] rehydrate skip %s", sched.id)
    logger.info("[scheduler] rehydrated %d jobs from DB", n)
    return n


def get_next_fire_at(schedule_id: uuid.UUID) -> datetime | None:
    """读取内存 scheduler 中某 job 的下次触发时间，方便 API 透出。"""
    if _scheduler is None:
        return None
    j = _scheduler.get_job(_make_job_id(schedule_id))
    return j.next_run_time if j else None


# ─────────────────────────── Lifespan ───────────────────────────
async def start() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")  # V7.0 · 钉死北京时区，cron「7点」= 北京7点
    _scheduler.start()
    logger.info("[scheduler] AsyncIOScheduler started (tz=Asia/Shanghai)")
    await rehydrate_from_db()
    # 系统级定时任务（与 user-defined MissionSchedule 区隔；id 用 sys-* 前缀）
    _register_system_jobs()


def _register_system_jobs() -> None:
    """V55 worker_invocation_log 90d TTL + V16 escalation auto-dismiss 每日 02:00 跑。"""
    if _scheduler is None:
        return
    # 已注册则跳过（防 rehydrate 重入）
    if _scheduler.get_job("sys-housekeeping-daily"):
        return
    _scheduler.add_job(
        _system_housekeeping_job,
        trigger=CronTrigger.from_crontab("0 2 * * *"),
        id="sys-housekeeping-daily",
        name="housekeeping (V55 TTL + V16 auto-dismiss)",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    logger.info("[scheduler] registered sys-housekeeping-daily (02:00 every day)")

    # ADR-025 D1 · 平台 worker 健康自检改为 dispatcher mission 的**可见 MissionSchedule**（6h，
    # 调度 tab 可见可调），由 ensure_worker_optimization_super 挂载、rehydrate_from_db 注册。
    # 不再用平台 cron sys-worker-health（已退役）。


async def _system_housekeeping_job() -> None:
    """V55 + V16 + V21 每日清理。失败容错不重抛。"""
    from sqlalchemy import text as _sql_text
    from app.core import system_settings as _ss

    try:
        async with _open_session() as db:
            ttl_days = await _ss.get_int(db, "worker_invocation_log.ttl_days", 90)
            dismiss_days = await _ss.get_int(db, "escalation.auto_dismiss_days", 7)
            # V55 删超过 TTL 的 worker_invocation_log
            del_res = await db.execute(_sql_text(
                "DELETE FROM worker_invocation_log "
                "WHERE started_at < now() - make_interval(days => :d)"
            ), {"d": ttl_days})
            # V16/V21 auto-dismiss pending escalation > N 天
            dis_res = await db.execute(_sql_text("""
                UPDATE mission_escalations
                   SET status='dismissed',
                       resolution_summary='auto-dismissed by V16/V21 ('|| :d ||'d timeout)',
                       resolved_at=now(),
                       resolved_by='system'
                 WHERE status IN ('pending','delivered')
                   AND created_at < now() - make_interval(days => :d)
            """), {"d": dismiss_days})
            await db.commit()
            logger.info(
                "📊 housekeeping: wil_deleted=%d esc_dismissed=%d",
                del_res.rowcount or 0, dis_res.rowcount or 0,
            )
    except Exception:
        logger.exception("[housekeeping] failed")


async def stop() -> None:
    global _scheduler
    if _scheduler is None:
        return
    with suppress(Exception):
        _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("[scheduler] shutdown")
