"""后台 fire-and-forget 任务注册。

病根：`asyncio.create_task(...)` 的返回值若不被持有，event loop 只保留**弱引用**，
长跑任务（escalation 投递 / 审批后推进 super）可能在完成前被 GC 掉，导致投递悄悄丢失。

解法：统一用 `spawn()`——把 task 放进模块级强引用集合，完成后回调自动移除。
"""
from __future__ import annotations

import asyncio
from typing import Any, Coroutine

_TASKS: set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return task


def pending_count() -> int:
    """当前在飞的后台任务数（测试 / 排障用）。"""
    return len(_TASKS)
