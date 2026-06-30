"""Mission Lifecycle 状态机 · v6.F · 单一权威。

CONTEXT.md > "Lifecycle 状态机（Mission 级）" 是唯一图。

不变式：
- v3 老字段 `runtime_status` 在 Phase A 后退化为本模块 derived view
- 所有 lifecycle 写入路径只能过 transition() 校验，外部不再裸 UPDATE
- enum 用 str 兼容 JSON / DB / pydantic

测试在 tests/test_v6_lifecycle.py，公共接口 = Lifecycle enum + transition() + is_alive() + can_trigger_tick()。
"""
from __future__ import annotations

import enum


class Lifecycle(str, enum.Enum):
    """Mission 业务状态机的 7 个合法状态。"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED_WAITING_CAPABILITY = "paused_waiting_capability"
    PAUSED_CLARIFICATION = "paused_clarification"
    # ADR-028 D4 · 阶段跑完、无门、无外部 pending → 必落此态。调度拉起即恢复 running。
    PAUSED_IDLE = "paused_idle"
    STOPPING = "stopping"
    ERROR = "error"


class LifecycleAction(str, enum.Enum):
    """合法 transition action。"""
    START = "start"
    STOP = "stop"
    PAUSE_FOR_CAPABILITY = "pause_for_capability"
    PAUSE_FOR_CLARIFICATION = "pause_for_clarification"
    PAUSE_IDLE = "pause_idle"  # ADR-028 D4 · 阶段收尾必落
    RESUME = "resume"
    RESOLVE_CLARIFICATION = "resolve_clarification"
    RESTART = "restart"
    EXCEPTION = "exception"


class InvalidLifecycleTransition(Exception):
    """当 caller 试图执行非法转换时抛；caller 应 catch 并报告 user 当前状态。"""
    def __init__(self, current: Lifecycle, action: LifecycleAction) -> None:
        super().__init__(f"非法 Lifecycle 转换：{current.value} ─{action.value}→ ?")
        self.current = current
        self.action = action


# 合法转换表：source state → {action: dest state}
# 不在表里的组合即非法 → 抛 InvalidLifecycleTransition
_TRANSITIONS: dict[Lifecycle, dict[LifecycleAction, Lifecycle]] = {
    Lifecycle.STOPPED: {
        LifecycleAction.START: Lifecycle.RUNNING,
        LifecycleAction.RESTART: Lifecycle.RUNNING,
    },
    Lifecycle.STARTING: {
        LifecycleAction.START: Lifecycle.RUNNING,  # idempotent 二次 start
        LifecycleAction.STOP: Lifecycle.STOPPED,
        LifecycleAction.EXCEPTION: Lifecycle.ERROR,
    },
    Lifecycle.RUNNING: {
        LifecycleAction.STOP: Lifecycle.STOPPED,
        LifecycleAction.PAUSE_FOR_CAPABILITY: Lifecycle.PAUSED_WAITING_CAPABILITY,
        LifecycleAction.PAUSE_FOR_CLARIFICATION: Lifecycle.PAUSED_CLARIFICATION,
        LifecycleAction.PAUSE_IDLE: Lifecycle.PAUSED_IDLE,  # ADR-028 D4 · 阶段收尾必落
        LifecycleAction.EXCEPTION: Lifecycle.ERROR,
        LifecycleAction.RESTART: Lifecycle.RUNNING,  # idempotent
    },
    # ADR-028 D4 · paused_idle 是「调度拉起→跑一轮→必落」机制的恢复点：
    # cron(START) / 用户消息(RESUME) 拉回 running；用户显式 STOP 收停。
    Lifecycle.PAUSED_IDLE: {
        LifecycleAction.START: Lifecycle.RUNNING,
        LifecycleAction.RESUME: Lifecycle.RUNNING,
        LifecycleAction.STOP: Lifecycle.STOPPED,
    },
    Lifecycle.PAUSED_WAITING_CAPABILITY: {
        LifecycleAction.RESUME: Lifecycle.RUNNING,
        LifecycleAction.STOP: Lifecycle.STOPPED,
    },
    Lifecycle.PAUSED_CLARIFICATION: {
        LifecycleAction.RESOLVE_CLARIFICATION: Lifecycle.RUNNING,
        LifecycleAction.STOP: Lifecycle.STOPPED,
    },
    Lifecycle.STOPPING: {
        LifecycleAction.STOP: Lifecycle.STOPPED,  # idempotent
    },
    Lifecycle.ERROR: {
        LifecycleAction.RESTART: Lifecycle.RUNNING,
        LifecycleAction.STOP: Lifecycle.STOPPED,
    },
}


def transition(current: Lifecycle, action: LifecycleAction) -> Lifecycle:
    """纯函数：计算目标状态。非法转换抛 InvalidLifecycleTransition。"""
    table = _TRANSITIONS.get(current, {})
    target = table.get(action)
    if target is None:
        raise InvalidLifecycleTransition(current, action)
    return target


# 「活着」（chat handler / scheduler 用来判断是否还能交互）
_ALIVE = {
    Lifecycle.STARTING,
    Lifecycle.RUNNING,
    Lifecycle.PAUSED_WAITING_CAPABILITY,
    Lifecycle.PAUSED_CLARIFICATION,
    Lifecycle.PAUSED_IDLE,  # ADR-028 D4 · 临时阻塞，scheduler 等待拉起
}


def is_alive(state: Lifecycle) -> bool:
    """mission 是否处于"活"状态（包含 paused — 这些是临时阻塞，scheduler 等就行）。

    STOPPED / STOPPING / ERROR → False（caller 应展示 stopped UI）
    """
    return state in _ALIVE


# 「可以触发新 tick」（chat handler 决定要不要立即 dispatch）
_CAN_TICK = {Lifecycle.RUNNING}


def can_trigger_tick(state: Lifecycle) -> bool:
    """只有 RUNNING 状态可立即触发 tick；paused 状态消息进队等 resume。"""
    return state in _CAN_TICK
