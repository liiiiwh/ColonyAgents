"""SSE 心跳合并器（订阅保活）。

把一个 async 事件源（event_bus 订阅生成器）转成「事件 + 周期心跳」流，给 SSE relay 用。

核心不变式（曾出过 bug 的点）：心跳超时**绝不取消** source 的挂起 `__anext__()`。
原实现每次心跳 `sub_task.cancel()`，CancelledError 抛进订阅生成器触发其 finally →
注销订阅 → 流断。表现：用户盯着审批方案看 >30s 再点确认时，decide 触发的 tick 事件
publish 到已死订阅 → 丢失，必须手动刷新才看到。这里改成保活同一个 pending task，
只在真正退出（客户端断开 / 到 deadline / 异常）时才取消并 aclose() 注销订阅。
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from typing import Any, Callable

# 心跳哨兵：调用方据此 yield 自己的 heartbeat 帧（与事件区分）
HEARTBEAT: Any = object()


async def iter_with_heartbeat(
    source: AsyncIterator[dict[str, Any]],
    *,
    heartbeat_interval: float,
    deadline: float,
    time_fn: Callable[[], float] = time.monotonic,
) -> AsyncIterator[Any]:
    """消费 source，正常 yield 其事件；每 heartbeat_interval 秒无事件则 yield HEARTBEAT。

    - 心跳期间保活同一个 `source.__anext__()`（不 cancel）→ 订阅不被销毁。
    - 到 time_fn() >= deadline 结束；source EOF 也结束。
    - 退出时取消挂起的 __anext__ 并 aclose() source（确保订阅注销，channel 不泄漏）。
    """
    pending: asyncio.Future | None = None
    try:
        while time_fn() < deadline:
            if pending is None:
                pending = asyncio.ensure_future(source.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_interval)
            if pending in done:
                try:
                    evt = pending.result()
                except StopAsyncIteration:
                    pending = None
                    return
                pending = None  # 已消费，下轮新建一个 __anext__
                yield evt
            else:
                # 心跳：pending 保持存活，订阅不动
                yield HEARTBEAT
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with contextlib.suppress(Exception):
                await pending
        with contextlib.suppress(Exception):
            await source.aclose()
