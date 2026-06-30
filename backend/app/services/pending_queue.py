"""R4-5 · pending_queue · super_pending_messages 表的持久化队列 CRUD。

从 super_inbox 拆出：只管用户消息队列（enqueue / pop / count）。
不碰 in-memory tick 注册表（那在 tick_lifecycle.py）。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import text as _sql_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def enqueue_user_message(
    db: AsyncSession,
    mission_id: uuid.UUID,
    super_agent_id: uuid.UUID,
    content: str,
    *,
    meta: dict | None = None,
    max_pending: int = 20,
    max_content_kb: int = 50,
) -> dict:
    """V4 · 把用户消息写入 super 的 pending 队列。

    F3/R-F3：单条 content > max_content_kb → S3 offload + 替换 URL。
    防 DoS：pending >= max_pending → reject。
    """
    cur = (await db.execute(_sql_text(
        "SELECT COUNT(*) FROM super_pending_messages "
        "WHERE super_mission_id=:pid AND status='pending'"
    ), {"pid": str(mission_id)})).scalar() or 0
    if cur >= max_pending:
        return {
            "ok": False,
            "error": f"pending queue 已满 ({cur}/{max_pending})；先让 super 处理一些消息再发",
        }
    final_content = content or ""
    extra_meta = dict(meta or {})
    size_bytes = len(final_content.encode("utf-8"))
    cap = max(5, int(max_content_kb)) * 1024
    if size_bytes > cap:
        try:
            from app.services.storage_service import get_storage
            import hashlib
            digest = hashlib.sha256(final_content.encode("utf-8")).hexdigest()[:16]
            key = f"colony/super-pending/{mission_id}/{digest}.txt"
            store = get_storage()
            url = await store.upload(key, final_content.encode("utf-8"), content_type="text/plain; charset=utf-8")
            snippet = final_content[: min(2000, cap // 4)]
            extra_meta["v38_offloaded"] = True
            extra_meta["v38_url"] = url
            extra_meta["v38_orig_bytes"] = size_bytes
            final_content = (
                f"⚠️ V38: 内容 {size_bytes} bytes > {cap} bytes 上限，已转 S3。\n\n"
                f"URL: {url}\n\n"
                f"--- 前 {len(snippet)} 字符预览 ---\n{snippet}"
            )
        except Exception:
            logger.exception("[pending_queue] V38 offload 失败，截断")
            extra_meta["v38_truncated"] = True
            extra_meta["v38_orig_bytes"] = size_bytes
            final_content = final_content[:cap] + f"\n\n... [V38 截断；原始 {size_bytes} bytes]"
    row = (await db.execute(_sql_text("""
        INSERT INTO super_pending_messages (super_mission_id, super_agent_id, content, meta, status)
        VALUES (:pid, :sid, :c, CAST(:m AS jsonb), 'pending')
        RETURNING id, created_at
    """), {
        "pid": str(mission_id),
        "sid": str(super_agent_id),
        "c": final_content,
        "m": __import__("json").dumps(extra_meta, ensure_ascii=False),
    })).mappings().one()
    await db.commit()
    return {
        "ok": True,
        "message_id": str(row["id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "queue_size_after": cur + 1,
        "v38_offloaded": extra_meta.get("v38_offloaded", False),
    }


async def pop_pending_messages(
    db: AsyncSession,
    mission_id: uuid.UUID,
) -> list[dict]:
    """run_once 入口调；原子 fetch pending + mark consumed（R-F1 事务包住）。"""
    rows = (await db.execute(_sql_text("""
        SELECT id, content, meta, created_at
          FROM super_pending_messages
         WHERE super_mission_id = :pid AND status = 'pending'
         ORDER BY created_at ASC
         FOR UPDATE SKIP LOCKED
    """), {"pid": str(mission_id)})).mappings().all()
    if not rows:
        return []
    from sqlalchemy import bindparam
    ids = [r["id"] for r in rows]
    stmt = _sql_text(
        "UPDATE super_pending_messages SET status='consumed', consumed_at=now() WHERE id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    await db.execute(stmt, {"ids": ids})
    await db.commit()
    return [
        {
            "id": str(r["id"]),
            "content": r["content"],
            "meta": r["meta"] or {},
            "created_at": r["created_at"],
        }
        for r in rows
    ]


async def count_pending(db: AsyncSession, mission_id: uuid.UUID) -> int:
    return (await db.execute(_sql_text(
        "SELECT COUNT(*) FROM super_pending_messages "
        "WHERE super_mission_id=:pid AND status='pending'"
    ), {"pid": str(mission_id)})).scalar() or 0
