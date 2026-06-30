"""R5-1 · EventTranslator · LangGraph astream_events v2 → AI SDK SSE 协议翻译（纯函数）。

stream_service 最后一个热路径纯核心。30+ 边界：stream/tool/error/thinking-vs-final 分段。
不需 DB / 网络 / LLM 实例。
"""
from __future__ import annotations

import json

import pytest


def _parse(out):
    """把 [(sse_line, trace), ...] 解析成 [(event_dict, trace), ...]。"""
    parsed = []
    for sse_line, trace in out:
        assert sse_line.startswith("data: ")
        parsed.append((json.loads(sse_line[6:].strip()), trace))
    return parsed


class _FakeChunk:
    def __init__(self, content):
        self.content = content


def _stream_evt(content):
    return {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk(content)}}


class _FakeOutput:
    def __init__(self, tool_calls=None):
        self.tool_calls = tool_calls or []
        self.usage_metadata = {}


def test_stream_delta_accumulates_buffer():
    from app.domain.stream.event_translator import emit_llm_event
    buf = []
    out = emit_llm_event(_stream_evt("你好"), "t1", buf, [], [])
    ev = _parse(out)
    assert ev[0][0]["type"] == "text-delta"
    assert ev[0][0]["delta"] == "你好"
    assert buf == ["你好"]


def test_stream_content_block_array_joined():
    """Gemini/Anthropic content block 数组 → 拼接。"""
    from app.domain.stream.event_translator import emit_llm_event
    buf = []
    evt = {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk([{"text": "a"}, {"text": "b"}])}}
    out = emit_llm_event(evt, "t1", buf, [], [])
    assert _parse(out)[0][0]["delta"] == "ab"


def test_tool_start_emits_input_available():
    from app.domain.stream.event_translator import emit_llm_event
    evt = {"event": "on_tool_start", "run_id": "r1", "name": "search", "data": {"input": {"q": "x"}}}
    ev = _parse(emit_llm_event(evt, "t1", [], [], []))
    assert ev[0][0]["type"] == "tool-input-available"
    assert ev[0][0]["toolName"] == "search"
    assert ev[0][0]["input"] == {"q": "x"}


def test_tool_end_emits_output_available():
    from app.domain.stream.event_translator import emit_llm_event
    evt = {"event": "on_tool_end", "run_id": "r1", "name": "search", "data": {"output": "found"}}
    ev = _parse(emit_llm_event(evt, "t1", [], [], []))
    assert ev[0][0]["type"] == "tool-output-available"
    assert ev[0][0]["output"] == "found"


def test_chat_model_end_with_tool_calls_archives_thinking():
    """有 tool_calls → 当前 buffer 是中间 narration → 归档 thinking_segments。"""
    from app.domain.stream.event_translator import emit_llm_event
    buf = ["我先想想"]
    thinking, final = [], []
    evt = {"event": "on_chat_model_end", "name": "x", "data": {"output": _FakeOutput(tool_calls=[{"name": "t"}])}}
    ev = _parse(emit_llm_event(evt, "t1", buf, thinking, final))
    assert thinking == ["我先想想"]
    assert final == []
    assert buf == []  # cleared
    assert ev[0][0]["type"] == "data-text-segment-end"
    assert ev[0][0]["data"]["has_tool_calls"] is True


def test_chat_model_end_without_tool_calls_archives_final():
    """无 tool_calls → 最终面向用户回复 → 归档 final_reply_parts。"""
    from app.domain.stream.event_translator import emit_llm_event
    buf = ["最终回复"]
    thinking, final = [], []
    evt = {"event": "on_chat_model_end", "name": "x", "data": {"output": _FakeOutput(tool_calls=[])}}
    emit_llm_event(evt, "t1", buf, thinking, final)
    assert final == ["最终回复"]
    assert thinking == []
    assert buf == []


def test_error_struct_emits_data_error_and_sets_error_info():
    from app.domain.stream.event_translator import emit_llm_event
    err_info = {}
    evt = {"__error_struct__": True, "user_message": "上游 502", "error_code": "BAD_GATEWAY",
           "request_id": "req1", "retriable": True, "attempt_count": 2}
    ev = _parse(emit_llm_event(evt, "t1", [], [], [], error_info=err_info))
    types = [e[0]["type"] for e in ev]
    assert "data-error" in types
    assert "text-delta" in types
    assert err_info["error_code"] == "BAD_GATEWAY"
    assert err_info["request_id"] == "req1"


def test_non_dict_event_ignored():
    from app.domain.stream.event_translator import emit_llm_event
    assert emit_llm_event("not a dict", "t1", [], [], []) == []
