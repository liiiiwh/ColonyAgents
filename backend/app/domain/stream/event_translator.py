"""R5-1 · EventTranslator · LangGraph astream_events v2 → AI SDK SSE 协议翻译。

stream_service 热路径里最后一个纯核心：把 LangGraph 事件翻译成前端 AI SDK data-stream
协议事件。无 DB / 网络 / LLM 实例，纯函数（按文档 mutate 传入的 buffer）。

文本分段逻辑（核心）：
- text-delta 累积到 segment_buffer
- on_chat_model_end：
    * tool_calls > 0  → 该 LLM call 是中间推理/分派前 narration → buffer 归档 thinking_segments
    * tool_calls == 0 → 最终面向用户回复 → buffer 归档 final_reply_parts
"""
from __future__ import annotations

import json
from typing import Any


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def emit_llm_event(
    evt: Any,
    text_id: str,
    segment_buffer: list[str],
    thinking_segments: list[str],
    final_reply_parts: list[str],
    error_info: dict[str, Any] | None = None,
) -> list[tuple[str, dict | None]]:
    """LangGraph 事件 → [(sse_line, trace_payload_or_None), ...]。"""
    out: list[tuple[str, dict | None]] = []
    if not isinstance(evt, dict):
        return out

    # 结构化错误（来自 _drive_llm 重试耗尽）
    if "__error_struct__" in evt:
        user_msg = evt.get("user_message", "AI 服务出现错误，请稍后重试")
        request_id = str(evt.get("request_id", ""))
        error_code = str(evt.get("error_code", "LLM_ERROR"))
        retriable = bool(evt.get("retriable", False))
        attempt_count = int(evt.get("attempt_count", 1))
        if error_info is not None:
            error_info["error_code"] = error_code
            error_info["user_message"] = user_msg
            error_info["request_id"] = request_id
            error_info["retriable"] = retriable
            error_info["attempt_count"] = attempt_count
        error_event: dict[str, Any] = {
            "type": "data-error",
            "data": {
                "message": user_msg,
                "error_code": error_code,
                "retriable": retriable,
                "attempt_count": attempt_count,
                "request_id": request_id,
            },
        }
        delta_text = f"\n\n❌ {user_msg}"
        if request_id:
            delta_text += f"\n请求 ID：{request_id}"
        text_event = {"type": "text-delta", "id": text_id, "delta": delta_text}
        segment_buffer.append(delta_text)
        out.append((_sse(error_event), {"type": "data-error", "data": error_event["data"]}))
        out.append((_sse(text_event), None))
        return out

    if "__error__" in evt:
        payload = {"type": "text-delta", "id": text_id, "delta": f"\n\n❌ 执行错误：{evt['__error__']}"}
        segment_buffer.append(f"\n\n❌ 执行错误：{evt['__error__']}")
        out.append((_sse(payload), {"type": "error", "error": evt["__error__"]}))
        return out

    kind = evt.get("event")
    if kind == "on_chat_model_stream":
        chunk = evt.get("data", {}).get("chunk")
        content = getattr(chunk, "content", "") if chunk is not None else ""
        if isinstance(content, list):
            pieces = [b.get("text", "") if isinstance(b, dict) else str(b) for b in content]
            content = "".join(pieces)
        if content:
            segment_buffer.append(content)
            out.append((_sse({"type": "text-delta", "id": text_id, "delta": content}), None))
    elif kind == "on_tool_start":
        payload = {
            "type": "tool-input-available",
            "toolCallId": str(evt.get("run_id", "")),
            "toolName": evt.get("name", "tool"),
            "input": evt.get("data", {}).get("input", {}),
        }
        out.append((_sse(payload), payload))
    elif kind == "on_tool_end":
        output = evt.get("data", {}).get("output", "")
        if hasattr(output, "content"):
            output = output.content
        payload = {
            "type": "tool-output-available",
            "toolCallId": str(evt.get("run_id", "")),
            "toolName": evt.get("name", "tool"),
            "output": str(output),
        }
        out.append((_sse(payload), payload))
    elif kind == "on_chat_model_end":
        output = evt.get("data", {}).get("output")
        tc = getattr(output, "tool_calls", None) if output is not None else None
        um = (
            (getattr(output, "usage_metadata", None) or getattr(output, "response_metadata", {}))
            if output is not None
            else {}
        )
        has_tool_calls = bool(tc)
        this_text = "".join(segment_buffer).strip()
        segment_buffer.clear()
        if has_tool_calls:
            if this_text:
                thinking_segments.append(this_text)
        else:
            if this_text:
                final_reply_parts.append(this_text)
        out.append((
            _sse({
                "type": "data-text-segment-end",
                "data": {"has_tool_calls": has_tool_calls, "text": this_text},
            }),
            {
                "type": "chat-model-end",
                "name": evt.get("name", ""),
                "tool_calls": tc if tc else [],
                "has_tool_calls": has_tool_calls,
                "text": this_text,
                "usage": um if isinstance(um, dict) else {},
            },
        ))
    return out
