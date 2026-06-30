"""V7.2 · tick 边界插入决策（纯函数）· ADR-007。

不再 cancel 当前 tick。用户消息进 pending_queue：
- super idle（不在跑 tick）+ runtime running → 立即触发新 tick
- super 正跑 tick → 排队等当前 tick 完（should_trigger_now=False）
- tick 一结束 → pending>0 则 auto-drain 开下一 tick
"""
from __future__ import annotations


def should_trigger_now(*, is_running: bool, runtime_status: str) -> bool:
    """用户消息进来时，是否立即触发新 tick。

    只有 super idle（没在跑 tick）且 runtime 是 running 时才立即触发；
    正在跑 tick 则不触发（消息排队，当前 tick 完后 auto-drain 接手）。
    """
    return (not is_running) and runtime_status == "running"


# ADR-028 D4 · 人工门 + 停止/错误：不消费 pending、调度 skip（凌驾 pending_count）。
# paused_idle / running / starting 才是「可继续」态。
_PAUSED_FOR_HUMAN = ("paused_clarification", "paused_waiting_capability")
_NO_DRAIN = (*_PAUSED_FOR_HUMAN, "stopped", "error")


def should_drain_after_tick(*, pending_count: int, lifecycle_status: str) -> bool:
    """ADR-028 D4 · 一个 tick 结束后，是否立即开下一 tick 处理 pending。

    人工门（paused_clarification/paused_waiting_capability）/ stopped / error →
    永不消费（pending 留到 resume / cron 再处理）；paused_idle / running 且有 pending → 消费。
    """
    if lifecycle_status in _NO_DRAIN:
        return False
    return pending_count > 0


def should_pause_idle_after_tick(
    *, err_msg: str | None, lifecycle_status: str, external_pending: int
) -> bool:
    """ADR-028 D4 · 一个 tick 收尾后是否转 paused_idle（「调度拉起→跑一轮→必落」）。

    必落 paused_idle 仅当：
    - tick 正常结束（err_msg=None；cancelled 也不算正常，那是人工门硬停）；
    - 期间没落人工门（lifecycle 仍为 running；若 tick 内 request_approval/request_new_capability
      已转 paused_for_human，则不能被 idle 覆盖）；
    - 无外部 pending（用户/调度 pending 尚未消费完 → 让 auto-drain 接着跑同一阶段，不提前 idle）。
    """
    if err_msg is not None:
        return False  # error / cancelled 都不落 idle（H5：error 走下次 cron 重试）
    if lifecycle_status != "running":
        return False  # 人工门已生效（或已 stopped），不覆盖
    return external_pending <= 0


def should_run_on_schedule(*, lifecycle_status: str) -> bool:
    """ADR-028 D4 · scheduler fire_one 按 mission lifecycle 决定 run/skip。

    - running / paused_idle / starting → RUN（paused_idle 到点拉新一轮）
    - paused_for_human / stopped / error → SKIP（观感=停调度，但不动 schedule.enabled）
    """
    return lifecycle_status not in _NO_DRAIN


def tick_wallclock_exceeded(*, elapsed_s: float, cap_s: float) -> bool:
    """ADR-028 D4 H6 · tick 墙钟封顶：单次 tick 跑超 cap_s 即收尾（break → 走 paused_idle，
    留待下次 cron 重拉），防「跑死/卡死 running」常驻空转。cap_s<=0 表示不限。"""
    return cap_s > 0 and elapsed_s >= cap_s
