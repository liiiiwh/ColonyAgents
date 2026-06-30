"""SSE 心跳合并器 · 订阅保活不变式。

bug：原 super_stream 心跳实现每 30s 超时就 cancel 订阅生成器的 __anext__()，CancelledError
触发订阅生成器 finally → 注销订阅 → 流断。用户「盯着审批方案看 >30s 再点确认」时，decide
触发的 tick 事件 publish 到已死订阅 → 丢失，必须手动刷新。

iter_with_heartbeat 必须：心跳期间保活同一个 pending __anext__()，订阅不被销毁。
"""
from __future__ import annotations

import asyncio
import time
import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def test_heartbeat_does_not_kill_subscription_then_event_still_delivered():
    """跨越多个心跳后再 publish，事件仍应送达（证明订阅没被心跳销毁）。"""
    from app.services.event_bus import InProcessBus
    from app.domain.stream.sse_heartbeat import iter_with_heartbeat, HEARTBEAT

    bus = InProcessBus()
    ch = uuid.uuid4()
    sub = bus.subscribe(ch)

    out: list = []
    deadline = time.monotonic() + 5

    async def consume():
        async for item in iter_with_heartbeat(
            sub, heartbeat_interval=0.05, deadline=deadline, time_fn=time.monotonic
        ):
            out.append(item)
            if item is not HEARTBEAT:
                break

    task = asyncio.create_task(consume())
    # 让若干心跳周期流逝（>= 3 个 heartbeat_interval）——订阅必须存活过这些心跳
    await asyncio.sleep(0.25)
    assert any(i is HEARTBEAT for i in out), "应已产生心跳"

    # 心跳之后再 publish —— 旧实现此时订阅已被销毁，事件永远收不到（task 卡死）
    await bus.publish(ch, {"type": "token", "delta": "hi"})
    await asyncio.wait_for(task, timeout=2)

    events = [i for i in out if i is not HEARTBEAT]
    assert events and events[-1]["type"] == "token", out


async def test_heartbeat_iterator_cleans_up_subscription_on_exit():
    """退出后订阅应被注销（channel 不泄漏）。"""
    from app.services.event_bus import InProcessBus
    from app.domain.stream.sse_heartbeat import iter_with_heartbeat, HEARTBEAT

    bus = InProcessBus()
    ch = uuid.uuid4()
    sub = bus.subscribe(ch)

    deadline = time.monotonic() + 5

    async def consume():
        async for item in iter_with_heartbeat(
            sub, heartbeat_interval=0.05, deadline=deadline, time_fn=time.monotonic
        ):
            if item is not HEARTBEAT:
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.12)
    await bus.publish(ch, {"type": "x"})
    await asyncio.wait_for(task, timeout=2)
    # 给 finally 清理一拍
    await asyncio.sleep(0.05)
    assert ch not in bus._channels or not bus._channels.get(ch), "退出后订阅应注销"
