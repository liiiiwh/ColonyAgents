"""V7.1 · StreamingExecutor Layer-1 · 共享的 astream_events → (sse, persist) 驱动核心。

chat 端（HTTP sink）和 daemon 端（persist+publish sink）复用同一个 drive。
TDD 用 fake executor（astream_events 返回预设事件列表），不需真 LLM。
"""
from __future__ import annotations

import json

import pytest


class _FakeChunk:
    def __init__(self, content):
        self.content = content


class _FakeOutput:
    def __init__(self, tool_calls=None):
        self.tool_calls = tool_calls or []
        self.usage_metadata = {}


class _FakeExecutor:
    """astream_events 返回预设事件序列。"""
    def __init__(self, events):
        self._events = events

    async def astream_events(self, _input, version="v2"):
        for e in self._events:
            yield e


def _stream(content):
    return {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk(content)}}


def _end(tool_calls=None):
    return {"event": "on_chat_model_end", "name": "sup", "data": {"output": _FakeOutput(tool_calls)}}


@pytest.mark.asyncio
async def test_drive_yields_sse_for_text_deltas():
    from app.services.streaming_executor import drive_agent_events

    ex = _FakeExecutor([_stream("你"), _stream("好"), _end(tool_calls=[])])
    pieces = [p async for p in drive_agent_events(ex, [], text_id="t1")]
    sse_pieces = [p for p in pieces if p.sse]
    # 两条 text-delta + 一条 segment-end
    deltas = [json.loads(p.sse[6:])["delta"] for p in sse_pieces if '"text-delta"' in p.sse]
    assert deltas == ["你", "好"]


@pytest.mark.asyncio
async def test_drive_persists_final_assistant_text():
    """无 tool_calls 的 LLM end → 最终回复，产出 assistant persist 动作。"""
    from app.services.streaming_executor import drive_agent_events

    ex = _FakeExecutor([_stream("最终回复"), _end(tool_calls=[])])
    pieces = [p async for p in drive_agent_events(ex, [], text_id="t1")]
    persists = [p.persist for p in pieces if p.persist]
    assistant = [p for p in persists if p.get("kind") == "assistant"]
    assert assistant, persists
    assert assistant[0]["text"] == "最终回复"


@pytest.mark.asyncio
async def test_drive_archives_thinking_when_tool_calls():
    """有 tool_calls 的 LLM end → narration 归档 thinking persist。"""
    from app.services.streaming_executor import drive_agent_events

    ex = _FakeExecutor([_stream("我先想想"), _end(tool_calls=[{"name": "t"}])])
    pieces = [p async for p in drive_agent_events(ex, [], text_id="t1")]
    persists = [p.persist for p in pieces if p.persist]
    thinking = [p for p in persists if p.get("kind") == "thinking"]
    assert thinking, persists
    assert thinking[0]["text"] == "我先想想"


@pytest.mark.asyncio
async def test_drive_emits_trace_persist_for_tool_events():
    """tool-input/output 事件应产出 trace persist（落 agent_log）。"""
    from app.services.streaming_executor import drive_agent_events

    ex = _FakeExecutor([
        {"event": "on_tool_start", "run_id": "r1", "name": "search", "data": {"input": {"q": "x"}}},
        {"event": "on_tool_end", "run_id": "r1", "name": "search", "data": {"output": "found"}},
    ])
    pieces = [p async for p in drive_agent_events(ex, [], text_id="t1")]
    traces = [p.persist for p in pieces if p.persist and p.persist.get("kind") == "trace"]
    assert len(traces) == 2
    assert traces[0]["evt"]["type"] == "tool-input-available"
    assert traces[1]["evt"]["type"] == "tool-output-available"
