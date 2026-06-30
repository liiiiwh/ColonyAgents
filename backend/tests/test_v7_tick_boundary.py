"""V7.2 · tick 边界插入决策（纯函数）· 不 cancel，super 忙时排队，完即抽 pending。

ADR-007：
- super idle + runtime running → 用户消息立即触发新 tick
- super 正跑 tick → 不 cancel，消息进 pending_queue 等当前 tick 完
- tick 一结束 → pending>0 则立即开下一 tick（auto-drain）
"""
from __future__ import annotations

import pytest


def test_trigger_when_idle_and_running():
    from app.domain.tick_policy import should_trigger_now
    assert should_trigger_now(is_running=False, runtime_status="running") is True


def test_no_trigger_when_busy():
    """super 正跑 tick → 不触发（消息排队等当前 tick 完）。"""
    from app.domain.tick_policy import should_trigger_now
    assert should_trigger_now(is_running=True, runtime_status="running") is False


def test_no_trigger_when_stopped():
    from app.domain.tick_policy import should_trigger_now
    assert should_trigger_now(is_running=False, runtime_status="stopped") is False


def test_drain_after_tick_when_pending():
    from app.domain.tick_policy import should_drain_after_tick
    assert should_drain_after_tick(pending_count=2, lifecycle_status="running") is True


def test_no_drain_when_empty():
    from app.domain.tick_policy import should_drain_after_tick
    assert should_drain_after_tick(pending_count=0, lifecycle_status="running") is False


# ─────────────────────── ADR-028 D4 · lifecycle 门控 ───────────────────────


def test_drain_paused_idle_still_consumes():
    """ADR-028 D4：paused_idle 是恢复点；有外部 pending 仍应消费一轮。"""
    from app.domain.tick_policy import should_drain_after_tick
    assert should_drain_after_tick(pending_count=1, lifecycle_status="paused_idle") is True


@pytest.mark.parametrize("ls", [
    "paused_clarification", "paused_waiting_capability", "stopped", "error",
])
def test_no_drain_when_paused_for_human_or_stopped(ls):
    """ADR-028 D4：人工门/停止/错误态不消费 pending（凌驾 pending_count>0）。"""
    from app.domain.tick_policy import should_drain_after_tick
    assert should_drain_after_tick(pending_count=5, lifecycle_status=ls) is False


def test_trigger_now_for_paused_idle():
    """ADR-028 D4：用户消息可立即触发 paused_idle 的新一轮（runtime 仍 running）。"""
    from app.domain.tick_policy import should_trigger_now
    assert should_trigger_now(is_running=False, runtime_status="running") is True


def test_pause_idle_after_normal_tick():
    """ADR-028 D4：tick 正常结束(err=None) + 无门(仍 running) + 无外部 pending → paused_idle。"""
    from app.domain.tick_policy import should_pause_idle_after_tick
    assert should_pause_idle_after_tick(
        err_msg=None, lifecycle_status="running", external_pending=0,
    ) is True


def test_no_pause_idle_when_error():
    """ADR-028 D4：tick 异常 → 不落 paused_idle（H5：error 走下次 cron 重试）。"""
    from app.domain.tick_policy import should_pause_idle_after_tick
    assert should_pause_idle_after_tick(
        err_msg="invoke: boom", lifecycle_status="running", external_pending=0,
    ) is False


def test_no_pause_idle_when_force_human_gate():
    """ADR-028 D4：tick 中落了人工门（lifecycle 已非 running）→ 不覆盖成 paused_idle。"""
    from app.domain.tick_policy import should_pause_idle_after_tick
    for ls in ("paused_clarification", "paused_waiting_capability"):
        assert should_pause_idle_after_tick(
            err_msg=None, lifecycle_status=ls, external_pending=0,
        ) is False


def test_no_pause_idle_when_external_pending():
    """ADR-028 D4：还有外部 pending → 不 idle（auto-drain 接着消费同阶段）。"""
    from app.domain.tick_policy import should_pause_idle_after_tick
    assert should_pause_idle_after_tick(
        err_msg=None, lifecycle_status="running", external_pending=1,
    ) is False


def test_no_pause_idle_when_cancelled():
    """ADR-028 D4：被 cancel 的 tick（人工门硬停）不落 paused_idle。"""
    from app.domain.tick_policy import should_pause_idle_after_tick
    assert should_pause_idle_after_tick(
        err_msg="cancelled_by_user_chat", lifecycle_status="running", external_pending=0,
    ) is False


def test_schedule_should_run_by_lifecycle():
    """ADR-028 D4：fire_one 按 lifecycle 决定 run/skip。
    running / paused_idle → run；paused_for_human / stopped / error → skip。"""
    from app.domain.tick_policy import should_run_on_schedule
    assert should_run_on_schedule(lifecycle_status="running") is True
    assert should_run_on_schedule(lifecycle_status="paused_idle") is True
    assert should_run_on_schedule(lifecycle_status="paused_clarification") is False
    assert should_run_on_schedule(lifecycle_status="paused_waiting_capability") is False
    assert should_run_on_schedule(lifecycle_status="stopped") is False
    assert should_run_on_schedule(lifecycle_status="error") is False
    # starting 视为可跑（即将 running）
    assert should_run_on_schedule(lifecycle_status="starting") is True
