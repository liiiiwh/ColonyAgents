"""V7.2 · daemon sink · 把 StreamPiece 落成 session 消息（→ append_message 自动 publish event_bus）。

这是 daemon 走流式的关键：每个 LLM/tool/thinking/assistant 事件实时进 session chat。
TDD 用 fake append_fn 验证 kind→role/meta 映射，不碰真 DB。
"""
from __future__ import annotations

import pytest

from app.services.streaming_executor import StreamPiece


class _Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, *, role, content, meta):
        self.calls.append({"role": role, "content": content, "meta": meta})


@pytest.mark.asyncio
async def test_trace_piece_persists_as_agent_log_with_raw():
    from app.services.daemon_sink import persist_stream_piece
    rec = _Recorder()
    piece = StreamPiece(persist={"kind": "trace", "evt": {"type": "tool-input-available", "toolName": "search"}})
    await persist_stream_piece(rec, piece, turn_id="t1", seq=0)
    assert len(rec.calls) == 1
    c = rec.calls[0]
    assert c["role"] == "agent_log"
    assert c["meta"]["event_type"] == "tool-input-available"
    assert c["meta"]["raw"]["toolName"] == "search"
    assert c["meta"]["turn_id"] == "t1"


@pytest.mark.asyncio
async def test_thinking_piece_persists_as_agent_log_thinking_segment():
    from app.services.daemon_sink import persist_stream_piece
    rec = _Recorder()
    piece = StreamPiece(persist={"kind": "thinking", "text": "我先想想"})
    await persist_stream_piece(rec, piece, turn_id="t1", seq=1)
    c = rec.calls[0]
    assert c["role"] == "agent_log"
    assert c["content"] == "我先想想"
    assert c["meta"]["event_type"] == "thinking-segment"


@pytest.mark.asyncio
async def test_assistant_piece_persists_as_assistant_message():
    from app.services.daemon_sink import persist_stream_piece
    rec = _Recorder()
    piece = StreamPiece(persist={"kind": "assistant", "text": "数据分析完成：涨粉 5%"})
    await persist_stream_piece(rec, piece, turn_id="t1", seq=2)
    c = rec.calls[0]
    assert c["role"] == "assistant"
    assert c["content"] == "数据分析完成：涨粉 5%"
    assert c["meta"]["agent"] == "supervisor"


@pytest.mark.asyncio
async def test_sse_only_piece_not_persisted():
    """纯 text-delta（sse 有、persist 无）不落库（避免逐 token 爆量）。"""
    from app.services.daemon_sink import persist_stream_piece
    rec = _Recorder()
    piece = StreamPiece(sse='data: {"type":"text-delta"}\n\n', persist=None)
    await persist_stream_piece(rec, piece, turn_id="t1", seq=0)
    assert rec.calls == []
