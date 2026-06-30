"""ADR-028 D4 · E2 · 协作式硬停 checkpoint。

drive_agent_events 必须在「每个 tool 结果后、下一次 LLM call 前」检查 cancel_event：
已 set → 立刻 raise CancelledError，保证人工门工具返回即停（而非「再蹦几个」）。
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.streaming_executor import drive_agent_events

pytestmark = pytest.mark.asyncio


class _FakeExecutor:
    """astream_events 桩：吐一个 tool_start、一个 tool_end，再吐第二个 tool_start。
    若 checkpoint 生效，cancel_event set 后第二个 tool_start 不应被 emit。"""

    def __init__(self, events):
        self._events = events

    def astream_events(self, _inputs, **_kw):
        async def _gen():
            for e in self._events:
                yield e
        return _gen()


def _tool_start(name, rid):
    return {"event": "on_tool_start", "name": name, "run_id": rid, "data": {"input": {}}}


def _tool_end(name, rid):
    return {"event": "on_tool_end", "name": name, "run_id": rid, "data": {"output": "ok"}}


async def test_checkpoint_stops_after_tool_when_cancelled():
    cancel = asyncio.Event()
    events = [
        _tool_start("request_approval", "r1"),
        _tool_end("request_approval", "r1"),   # ← 人工门工具返回；此后 cancel 已 set
        _tool_start("post_xhs", "r2"),          # ← 不应到达
        _tool_end("post_xhs", "r2"),
    ]
    ex = _FakeExecutor(events)

    seen_tools: list[str] = []

    async def _consume():
        async for piece in drive_agent_events(ex, [], cancel_event=cancel):
            if piece.persist and piece.persist.get("kind") == "trace":
                tr = piece.persist.get("evt") or {}
                # tool-input-available 标记 tool 开始
                if isinstance(tr, dict) and tr.get("type") == "tool-input-available":
                    seen_tools.append(tr.get("toolName"))
                    # 模拟人工门：request_approval 返回后落卡 → set cancel_event
                    if tr.get("toolName") == "request_approval":
                        cancel.set()

    # E2 修复：cancel_event set 后在 on_tool_end checkpoint **break**（而非 raise CancelledError，
    # 后者在 LangGraph astream_events 深层栈会触发 asyncio 取消级联 → RecursionError 崩 tick）。
    # break → 循环干净结束，不抛异常。
    await _consume()

    assert "request_approval" in seen_tools
    assert "post_xhs" not in seen_tools, "cancel 后不应再 emit 下一个 tool（E2 checkpoint break）"


async def test_no_cancel_runs_all_tools():
    """cancel_event 未 set → 正常跑完所有 tool。"""
    cancel = asyncio.Event()
    events = [
        _tool_start("a", "r1"), _tool_end("a", "r1"),
        _tool_start("b", "r2"), _tool_end("b", "r2"),
    ]
    ex = _FakeExecutor(events)
    seen: list[str] = []
    async for piece in drive_agent_events(ex, [], cancel_event=cancel):
        if piece.persist and piece.persist.get("kind") == "trace":
            tr = piece.persist.get("evt") or {}
            if isinstance(tr, dict) and tr.get("type") == "tool-input-available":
                seen.append(tr.get("toolName"))
    assert seen == ["a", "b"]
