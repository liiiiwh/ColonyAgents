"""v6.F · Lifecycle 状态机 tracer bullet。

CONTEXT.md > "Lifecycle 状态机（Mission 级）" 是唯一权威。

设计意图：
- 当前 runtime_status (v3) 和 lifecycle_status 二字段并存导致 bug（v5 修过）
- v6 起：Lifecycle enum 是唯一权威；LifecycleService.transition() 是唯一写入入口
- runtime_status 在 Phase A 后退化为 derived view（is_alive 计算）

测试只通过 public interface：Lifecycle enum + 转换合法性表（不打 DB）。
"""
from __future__ import annotations

import pytest


def test_lifecycle_enum_values_match_contextmd():
    """CONTEXT.md "Lifecycle 状态机（Mission 级）" 定义的 7 个状态都存在。"""
    from app.domain.lifecycle import Lifecycle
    assert Lifecycle.STOPPED.value == "stopped"
    assert Lifecycle.STARTING.value == "starting"
    assert Lifecycle.RUNNING.value == "running"
    assert Lifecycle.PAUSED_WAITING_CAPABILITY.value == "paused_waiting_capability"
    assert Lifecycle.PAUSED_CLARIFICATION.value == "paused_clarification"
    assert Lifecycle.STOPPING.value == "stopping"
    assert Lifecycle.ERROR.value == "error"


def test_transition_legal_paths():
    """合法转换：start / stop / pause_for_capability / resume / pause_for_clarification / error / restart."""
    from app.domain.lifecycle import Lifecycle, LifecycleAction, transition

    # stopped → running 走 start
    assert transition(Lifecycle.STOPPED, LifecycleAction.START) == Lifecycle.RUNNING
    # running → stopped 走 stop
    assert transition(Lifecycle.RUNNING, LifecycleAction.STOP) == Lifecycle.STOPPED
    # running → paused_waiting_capability
    assert transition(Lifecycle.RUNNING, LifecycleAction.PAUSE_FOR_CAPABILITY) == Lifecycle.PAUSED_WAITING_CAPABILITY
    # paused → resume → running
    assert transition(Lifecycle.PAUSED_WAITING_CAPABILITY, LifecycleAction.RESUME) == Lifecycle.RUNNING
    # running → paused_clarification
    assert transition(Lifecycle.RUNNING, LifecycleAction.PAUSE_FOR_CLARIFICATION) == Lifecycle.PAUSED_CLARIFICATION
    # paused_clarification → resolve → running
    assert transition(Lifecycle.PAUSED_CLARIFICATION, LifecycleAction.RESOLVE_CLARIFICATION) == Lifecycle.RUNNING
    # error → restart → running
    assert transition(Lifecycle.ERROR, LifecycleAction.RESTART) == Lifecycle.RUNNING
    # running → exception → error
    assert transition(Lifecycle.RUNNING, LifecycleAction.EXCEPTION) == Lifecycle.ERROR


def test_transition_illegal_raises():
    """非法转换 → InvalidLifecycleTransition; locality 保证."""
    from app.domain.lifecycle import (
        InvalidLifecycleTransition,
        Lifecycle,
        LifecycleAction,
        transition,
    )

    # stopped 不能直接 resume（必须先 start）
    with pytest.raises(InvalidLifecycleTransition):
        transition(Lifecycle.STOPPED, LifecycleAction.RESUME)
    # running 不能 start 第二次
    with pytest.raises(InvalidLifecycleTransition):
        transition(Lifecycle.RUNNING, LifecycleAction.START)
    # paused_clarification 不能 PAUSE_FOR_CAPABILITY（必须先 resolve）
    with pytest.raises(InvalidLifecycleTransition):
        transition(Lifecycle.PAUSED_CLARIFICATION, LifecycleAction.PAUSE_FOR_CAPABILITY)


def test_is_alive_helper_for_runtime_status_compat():
    """旧 runtime_status='running' 在 Phase A 后会被 derived 替代；
    is_alive 给老调用者一个一致的 bool 判断。
    """
    from app.domain.lifecycle import Lifecycle, is_alive
    assert is_alive(Lifecycle.RUNNING) is True
    assert is_alive(Lifecycle.STARTING) is True
    assert is_alive(Lifecycle.PAUSED_WAITING_CAPABILITY) is True  # 还活着只是等
    assert is_alive(Lifecycle.PAUSED_CLARIFICATION) is True
    assert is_alive(Lifecycle.STOPPED) is False
    assert is_alive(Lifecycle.STOPPING) is False
    assert is_alive(Lifecycle.ERROR) is False


def test_can_trigger_tick():
    """super tick 只在 RUNNING 状态触发；这是 chat handler / scheduler 的判断点。"""
    from app.domain.lifecycle import Lifecycle, can_trigger_tick
    assert can_trigger_tick(Lifecycle.RUNNING) is True
    # paused 状态不应触发新 tick（保留 super 当前等待）
    assert can_trigger_tick(Lifecycle.PAUSED_WAITING_CAPABILITY) is False
    assert can_trigger_tick(Lifecycle.PAUSED_CLARIFICATION) is False
    assert can_trigger_tick(Lifecycle.STOPPED) is False
    assert can_trigger_tick(Lifecycle.ERROR) is False


def test_lifecycle_serialization_is_string_enum():
    """JSON / API 传输用 string；Lifecycle 是 str enum。"""
    from app.domain.lifecycle import Lifecycle
    assert Lifecycle.RUNNING == "running"  # str compare 通过
    # JSON dump
    import json
    assert json.dumps({"lifecycle": Lifecycle.RUNNING}) == '{"lifecycle": "running"}'


def test_lifecycle_from_string_for_db_round_trip():
    """DB 里存的是 string，读取后能 Lifecycle(value) 还原。"""
    from app.domain.lifecycle import Lifecycle
    assert Lifecycle("running") == Lifecycle.RUNNING
    assert Lifecycle("paused_clarification") == Lifecycle.PAUSED_CLARIFICATION


# ─────────────────────── ADR-028 D4 · paused_idle ───────────────────────


def test_paused_idle_enum_exists():
    """ADR-028 D4：新增 paused_idle 状态 + PAUSE_IDLE 动作。"""
    from app.domain.lifecycle import Lifecycle, LifecycleAction
    assert Lifecycle.PAUSED_IDLE.value == "paused_idle"
    assert LifecycleAction.PAUSE_IDLE.value == "pause_idle"


def test_running_pause_idle_to_paused_idle():
    """ADR-028 D4：RUNNING --PAUSE_IDLE--> PAUSED_IDLE（阶段跑完必落）。"""
    from app.domain.lifecycle import Lifecycle, LifecycleAction, transition
    assert transition(Lifecycle.RUNNING, LifecycleAction.PAUSE_IDLE) == Lifecycle.PAUSED_IDLE


def test_paused_idle_resume_start_to_running():
    """ADR-028 D4：paused_idle 可被 cron(START)/用户(RESUME) 拉回 running。"""
    from app.domain.lifecycle import Lifecycle, LifecycleAction, transition
    assert transition(Lifecycle.PAUSED_IDLE, LifecycleAction.START) == Lifecycle.RUNNING
    assert transition(Lifecycle.PAUSED_IDLE, LifecycleAction.RESUME) == Lifecycle.RUNNING


def test_paused_idle_stop_to_stopped():
    """ADR-028 D4：paused_idle 可被用户显式 STOP。"""
    from app.domain.lifecycle import Lifecycle, LifecycleAction, transition
    assert transition(Lifecycle.PAUSED_IDLE, LifecycleAction.STOP) == Lifecycle.STOPPED


def test_paused_idle_is_alive_but_not_tickable():
    """ADR-028 D4：paused_idle 是临时阻塞（alive），但不立即 tick（由 scheduler 拉起）。"""
    from app.domain.lifecycle import Lifecycle, is_alive, can_trigger_tick
    assert is_alive(Lifecycle.PAUSED_IDLE) is True
    assert can_trigger_tick(Lifecycle.PAUSED_IDLE) is False
