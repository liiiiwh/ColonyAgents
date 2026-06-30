"""消息持久化服务：按 (mission_id, thread_key) 写入 / 读取一条 thread 的消息。

v6 · MessageInbox seam · 见 docs/adr/006-v6-session-model.md & 架构 review #4
所有 message 写入入口都应走 append_message —— 它会自动 publish event_bus，
让 SSE 订阅者（前端 chat 流）实时收到。直接 `Message(...)` + db.add 绕过这里
= SSE 偶发收不到 message 的根因（架构 review 报告 #4 已警示）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from contextlib import suppress

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message

logger = logging.getLogger(__name__)


async def append_message(
    db: AsyncSession,
    mission_id: uuid.UUID,
    thread_key: str,
    role: str,
    content: str,
    *,
    meta: dict | None = None,
    token_count: int | None = None,
    publish: bool = True,
) -> Message:
    """ADR-018 step5/H · 按 (mission_id, thread_key) 写一条消息（thread 解析缝消失）。

    一条消息 = 1 INSERT，0 派生：thread_key 由调用方用纯函数算出，不再 find-or-create branch 行。
    旧的 session_id/branch_id 列留 NULL（Slice X drop）。event_bus 推到 Mission 频道。"""
    msg = Message(
        mission_id=mission_id,
        thread_key=thread_key,
        role=role,
        content=content,
        meta=meta or {},
        token_count=token_count,
    )
    db.add(msg)
    await db.commit()
    # refresh is best-effort: the commit is authoritative (msg.id is set before add); refresh only
    # reloads server-default created_at, and can transiently fail mid-operation on the shared
    # streaming sqlite connection — never let that drop an already-committed message.
    with suppress(Exception):
        await db.refresh(msg)

    # v6 · 自动推 event_bus；任意 caller 调 append_message 都不会漏 SSE。
    # ADR-018 · channel = the Mission (mission_id)；一个 mission 的所有 thread 共用一个频道。
    if publish and mission_id is not None:
        try:
            from app.services.event_bus import bus as _bus
            await _bus.publish(mission_id, {
                "type": "message",
                "id": str(msg.id),
                "role": role,
                "content": (content or "")[:4000],
                "meta": meta or {},
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            })
        except Exception:
            logger.exception("[append_message] event_bus publish failed (不阻塞)")
    return msg


async def list_thread_messages(
    db: AsyncSession,
    mission_id: uuid.UUID,
    thread_key: str,
    *,
    include_compressed: bool = False,
    limit: int | None = None,
) -> Sequence[Message]:
    """ADR-018 step 3 · the read seam mirroring append_message's write seam.

    Reads a Thread's messages by the target keying (mission_id, thread_key) instead of the
    migration-era branch_id. During the dual-write window these return the same physical rows
    as `list_messages(branch_id)`; after step 5 (branch_id retires) this is the only read path."""
    stmt = (
        select(Message)
        .where(Message.mission_id == mission_id, Message.thread_key == thread_key)
        .order_by(Message.created_at.asc())
    )
    if not include_compressed:
        stmt = stmt.where(Message.is_compressed.is_(False))
    if limit:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()
