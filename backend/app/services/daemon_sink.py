"""V7.2 · daemon sink · StreamPiece → session 消息（ADR-007）。

daemon 走流式时，drive_agent_events 产出的每个 StreamPiece 经此落成消息。
append_fn 通常是 messaging_service.append_message 的偏函数（已绑定 db/session/branch），
它会自动 publish event_bus → /super/{slug}/stream 转发 → 前端实时看到 daemon 每一步。

kind → role 映射：
- trace      → agent_log（meta.raw 带完整事件，前端 toTimeline 重建工具卡）
- thinking   → agent_log（event_type=thinking-segment）
- assistant  → assistant（最终面向用户的回复）
- sse-only（persist=None）→ 不落库（纯 token 流，避免逐 token 爆量）
"""
from __future__ import annotations

from typing import Any, Callable, Awaitable

from app.services.streaming_executor import StreamPiece

AppendFn = Callable[..., Awaitable[Any]]


async def persist_stream_piece(
    append_fn: AppendFn,
    piece: StreamPiece,
    *,
    turn_id: str,
    seq: int,
) -> None:
    """把一个 StreamPiece 落库（仅 persist 非空时）。"""
    p = piece.persist
    if not p:
        return
    kind = p.get("kind")
    if kind == "trace":
        evt = p.get("evt") or {}
        await append_fn(
            role="agent_log",
            content="",
            meta={
                "turn_id": turn_id,
                "sequence": seq,
                "event_type": evt.get("type", "unknown"),
                "raw": evt,
                "source": "daemon_tick",
            },
        )
    elif kind == "thinking":
        await append_fn(
            role="agent_log",
            content=p.get("text", ""),
            meta={
                "turn_id": turn_id,
                "sequence": seq,
                "event_type": "thinking-segment",
                "source": "daemon_tick",
            },
        )
    elif kind == "assistant":
        await append_fn(
            role="assistant",
            content=p.get("text", ""),
            meta={"agent": "supervisor", "turn_id": turn_id, "source": "daemon_tick_reply"},
        )
