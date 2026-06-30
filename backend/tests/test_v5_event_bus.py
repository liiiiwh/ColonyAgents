"""v5 contract tests · event_bus + invoke_super stub。

不依赖 DB / 后端运行；纯单元。
"""
from __future__ import annotations

import asyncio
import uuid

import pytest


@pytest.mark.asyncio
async def test_inprocess_bus_publish_subscribe_basic():
    from app.services.event_bus import InProcessBus

    bus = InProcessBus()
    ch = uuid.uuid4()
    received: list[dict] = []

    async def consumer():
        async for evt in bus.subscribe(ch):
            received.append(evt)
            if len(received) >= 4:
                break

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)  # 让 consumer 注册
    for i, kind in enumerate(["worker_resolve", "worker_start", "worker_llm_invoke", "worker_done"]):
        await bus.publish(ch, {"type": kind, "call_id": "abc", "i": i})
    await asyncio.wait_for(task, timeout=2.0)

    assert [e["type"] for e in received] == [
        "worker_resolve", "worker_start", "worker_llm_invoke", "worker_done"
    ]
    assert all(e["call_id"] == "abc" for e in received)
    assert all("ts" in e for e in received)  # publish 自动盖 ts


@pytest.mark.asyncio
async def test_inprocess_bus_multi_subscribers():
    from app.services.event_bus import InProcessBus

    bus = InProcessBus()
    ch = uuid.uuid4()
    r1, r2 = [], []

    async def sub(out: list):
        async for evt in bus.subscribe(ch):
            out.append(evt)
            if len(out) >= 2:
                break

    t1 = asyncio.create_task(sub(r1))
    t2 = asyncio.create_task(sub(r2))
    await asyncio.sleep(0.05)
    await bus.publish(ch, {"type": "a"})
    await bus.publish(ch, {"type": "b"})
    await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2.0)

    assert [e["type"] for e in r1] == ["a", "b"]
    assert [e["type"] for e in r2] == ["a", "b"]


@pytest.mark.asyncio
async def test_inprocess_bus_isolated_channels():
    from app.services.event_bus import InProcessBus

    bus = InProcessBus()
    ch1, ch2 = uuid.uuid4(), uuid.uuid4()
    r1, r2 = [], []

    async def sub(ch, out):
        async for evt in bus.subscribe(ch):
            out.append(evt)
            break

    t1 = asyncio.create_task(sub(ch1, r1))
    t2 = asyncio.create_task(sub(ch2, r2))
    await asyncio.sleep(0.05)
    await bus.publish(ch1, {"type": "only_ch1"})
    await bus.publish(ch2, {"type": "only_ch2"})
    await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2.0)
    assert r1[0]["type"] == "only_ch1"
    assert r2[0]["type"] == "only_ch2"


@pytest.mark.asyncio
async def test_inprocess_bus_publish_to_empty_channel_noop():
    from app.services.event_bus import InProcessBus

    bus = InProcessBus()
    # 没人订阅；publish 不应抛
    await bus.publish(uuid.uuid4(), {"type": "x"})


def test_pg_notify_backend_stub_raises():
    from app.services.event_bus import PgNotifyBackend

    backend = PgNotifyBackend()
    with pytest.raises(NotImplementedError):
        asyncio.run(backend.publish(uuid.uuid4(), {"type": "x"}))


def test_invoke_super_stub_raises_not_implemented():
    """v5 锁：invoke_super 必抛 NotImplementedError；v6 才正式启用。"""
    from app.skills_builtin.super.super_dispatch_skills import invoke_super_tool
    from app.skills_builtin.context import BuiltinToolContext

    ctx = BuiltinToolContext()
    tool = invoke_super_tool(ctx)
    assert tool.name == "invoke_super"
    assert "v5 stub" in tool.description

    with pytest.raises(NotImplementedError):
        asyncio.run(tool.coroutine(super_ref="anything"))


def test_no_super_protocol_contains_invoke_super_word():
    """contract · 数据库种子或代码中不应有 super.protocol_md 含 'invoke_super' 字样。
    （v6 真正启用前，保证 LLM 不被错误教导）
    """
    import pathlib
    # 检查 init_db.py + seed_worker_catalog.py 不应含
    for p in [
        pathlib.Path("app/db/init_db.py"),
        pathlib.Path("app/db/seed_worker_catalog.py"),
    ]:
        text = p.read_text(encoding="utf-8")
        # 允许在注释 / docstring / 测试名里出现
        # 这里简化：检查没有出现在 .protocol_md 模板字符串里
        if "invoke_super(" in text or "调 invoke_super" in text or "invoke_super 调度" in text:
            assert False, f"{p} 含 invoke_super 调用示例；v5 不应教 LLM 使用"


# ─────────── ADR-029 · SSE 重放缓冲：订阅前发布的事件也能补齐（零延迟无丢包）───────────


@pytest.mark.asyncio
async def test_replay_delivers_events_published_before_subscribe():
    """核心不变式：publish 时无订阅者，事件进重放缓冲；随后订阅者连上**立即补齐**收到。

    修 SSE 连接空窗丢包（daemon tick 在前端 EventSource 连上前 publish approval_request →
    旧实现 fire-and-forget 直接丢 → 卡片渲染成「已关闭」需刷新）。"""
    from app.services.event_bus import InProcessBus

    bus = InProcessBus()
    ch = uuid.uuid4()
    # 无订阅者时 publish —— 必须被缓冲以供重放
    await bus.publish(ch, {"type": "approval_request", "request_id": "r1"})

    received: list[dict] = []

    async def consumer():
        async for evt in bus.subscribe(ch):
            received.append(evt)
            break

    t = asyncio.create_task(consumer())
    await asyncio.wait_for(t, timeout=2.0)
    assert received and received[0]["type"] == "approval_request"
    assert received[0]["request_id"] == "r1"


@pytest.mark.asyncio
async def test_replay_skips_stale_events_by_ttl():
    """重放只补最近 TTL 内的事件——久置 mission 重连不应重放陈旧事件。"""
    from app.services.event_bus import InProcessBus

    bus = InProcessBus()
    ch = uuid.uuid4()
    await bus.publish(ch, {"type": "ancient", "ts": 1.0})  # 远古 ts → 应被 TTL 滤掉
    await bus.publish(ch, {"type": "fresh", "request_id": "r2"})

    received: list[dict] = []

    async def consumer():
        async for evt in bus.subscribe(ch):
            received.append(evt)
            if evt.get("type") == "fresh":
                break

    t = asyncio.create_task(consumer())
    await asyncio.wait_for(t, timeout=2.0)
    types = [e["type"] for e in received]
    assert "fresh" in types
    assert "ancient" not in types


@pytest.mark.asyncio
async def test_replay_then_live_no_gap():
    """订阅后：先补齐重放，再无缝续接实时事件。"""
    from app.services.event_bus import InProcessBus

    bus = InProcessBus()
    ch = uuid.uuid4()
    await bus.publish(ch, {"type": "before", "n": 1})  # 订阅前

    received: list[dict] = []

    async def consumer():
        async for evt in bus.subscribe(ch):
            received.append(evt)
            if len(received) >= 2:
                break

    t = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)  # 让订阅注册
    await bus.publish(ch, {"type": "after", "n": 2})  # 订阅后实时
    await asyncio.wait_for(t, timeout=2.0)
    assert [e["type"] for e in received] == ["before", "after"]
