"""V7.1 · StreamingExecutor Layer-1 · 共享流式执行核心（ADR-007）。

把 LangGraph executor.astream_events 的事件流，经 event_translator 翻译，产出一串
StreamPiece(sse, persist, trace)。两个 sink 复用：

- HTTP sink（stream_chat_reply）：yield piece.sse 给客户端 + enqueue piece.persist
- daemon sink（V7.2）：忽略 sse，piece.persist → append_message（自动 publish event_bus）

本模块只管「事件 → piece 序列」；分支解析 / 重试 / DB 落库都在 sink 层，保持 Layer-1 纯。
"""
from __future__ import annotations

import asyncio
import logging
import uuid as _uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.domain.stream.event_translator import emit_llm_event

logger = logging.getLogger(__name__)


@dataclass
class StreamPiece:
    """一个流式产物。

    sse:     给 HTTP 客户端的 SSE 行（daemon sink 忽略）
    persist: 落库动作 {kind: 'trace'|'thinking'|'assistant', ...}（None = 不落库，纯 token 流）
    """
    sse: str | None = None
    persist: dict | None = None


async def drive_agent_events(
    executor: Any,
    input_messages: list,
    *,
    text_id: str | None = None,
    recursion_limit: int | None = None,
    cancel_event: "asyncio.Event | None" = None,
) -> AsyncIterator[StreamPiece]:
    """驱动 astream_events → 翻译 → 产出 StreamPiece 序列。

    segment 分段语义（与 stream_chat_reply 一致，via emit_llm_event）：
    - text-delta 累积；on_chat_model_end 时 has_tool_calls→thinking，否则→assistant
    - tool/error 事件作为 trace persist

    ADR-028 D4 · E2 协作式硬停：传入 cancel_event 时，在「每个 tool 结果（on_tool_end）后、
    下一次 LLM call 前」检查；已 set → raise CancelledError。保证人工门工具（request_approval /
    request_new_capability 落卡时 set 信号）一返回即停，而不是「再蹦几个」工具/LLM 调用。
    """
    text_id = text_id or str(_uuid.uuid4())
    segment_buffer: list[str] = []
    thinking_segments: list[str] = []
    final_reply_parts: list[str] = []

    # 已 emit 到 persist 的 thinking/final 数量（避免重复 flush）
    thinking_emitted = 0
    final_emitted = 0

    # recursion_limit 从 agent.max_iterations 透传（默认 LangGraph 25 对 super 偏低，
    # 多轮 tool（memory_read+起草+request_approval…）易撞限，导致 tick 报 GRAPH_RECURSION）。
    if recursion_limit:
        _stream = executor.astream_events(
            {"messages": input_messages}, version="v2",
            config={"recursion_limit": recursion_limit},
        )
    else:
        _stream = executor.astream_events({"messages": input_messages}, version="v2")
    async for evt in _stream:
        for sse_chunk, trace in emit_llm_event(
            evt, text_id, segment_buffer, thinking_segments, final_reply_parts
        ):
            # text-delta（trace=None）→ 纯 SSE，不落库
            if trace is None:
                yield StreamPiece(sse=sse_chunk, persist=None)
                continue
            # chat-model-end / tool / error → 既 SSE 又 trace 落库
            yield StreamPiece(sse=sse_chunk, persist={"kind": "trace", "evt": trace})

        # on_chat_model_end 后，emit_llm_event 已把段归档到 thinking/final 列表
        # → 这里把新增的段转成 thinking/assistant persist 动作
        while thinking_emitted < len(thinking_segments):
            yield StreamPiece(persist={"kind": "thinking", "text": thinking_segments[thinking_emitted]})
            thinking_emitted += 1
        while final_emitted < len(final_reply_parts):
            yield StreamPiece(persist={"kind": "assistant", "text": final_reply_parts[final_emitted]})
            final_emitted += 1

        # ADR-028 D4 · E2 checkpoint：tool 结果到达后（on_tool_end），若人工门已 set cancel_event，
        # 立刻停——下一个 astream_events 事件（下一次 LLM call）不再处理。
        # **必须 break 而非 raise CancelledError**：在 LangGraph astream_events 深层异步生成器栈里
        # 手动抛 CancelledError 会触发 asyncio 取消级联（child.cancel() 递归）→ RecursionError 崩 tick。
        # break 干净退出 async for → 生成器正常收尾 → tick 自然结束（lifecycle 已被人工门置 paused）。
        if (
            cancel_event is not None
            and cancel_event.is_set()
            and isinstance(evt, dict)
            and evt.get("event") == "on_tool_end"
        ):
            logger.info("[drive_agent_events] cancel_event set @on_tool_end → break（E2 协作停）")
            break
