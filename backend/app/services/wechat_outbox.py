"""WeChat outbox 业务：失败消息排队 + 用户首次发消息时触发 flush。"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt
from app.models.approvals import WechatClawbotAccount
from app.models.wechat_outbox import WechatOutbox

logger = logging.getLogger(__name__)


async def queue(
    db: AsyncSession,
    *,
    account_id: uuid.UUID,
    mission_id: uuid.UUID | None,
    failed_recipients: list[dict],  # [{user_id, error}]
    content: str,
    kind: str = "notification",
) -> None:
    """把失败的目标用户塞 outbox。"""
    for f in failed_recipients:
        row = WechatOutbox(
            account_id=account_id,
            mission_id=mission_id,
            target_wechat_id=f["user_id"],
            kind=kind,
            content=content,
            status="pending",
            attempt_count=1,
            last_error=f.get("error") or "",
        )
        db.add(row)
    await db.commit()


async def flush_for_user(
    db: AsyncSession,
    *,
    account_id: uuid.UUID,
    wechat_user_id: str,
) -> int:
    """用户主动给 bot 发消息后，poller 调它把积压消息一次性发出。

    返回成功推送数。失败 row 增加 attempt_count，不删（留观察）。
    """
    from app.services import wechat_clawbot

    rows = (
        await db.execute(
            select(WechatOutbox).where(
                WechatOutbox.account_id == account_id,
                WechatOutbox.target_wechat_id == wechat_user_id,
                WechatOutbox.status == "pending",
            ).order_by(WechatOutbox.created_at)
        )
    ).scalars().all()
    if not rows:
        return 0

    acc = await db.get(WechatClawbotAccount, account_id)
    if acc is None:
        return 0
    token = decrypt(acc.bot_token)
    ctx_tokens = dict(acc.context_tokens or {})
    sent = 0
    for row in rows:
        try:
            await wechat_clawbot.send_text(
                token=token,
                base_url=acc.base_url,
                to_user_id=wechat_user_id,
                text=row.content,
                context_token=str(ctx_tokens.get(wechat_user_id, "")),
            )
            row.status = "sent"
            from datetime import UTC, datetime as _dt
            row.sent_at = _dt.now(UTC)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            row.attempt_count += 1
            row.last_error = str(exc)[:500]
            logger.warning("[wechat_outbox] flush 失败 user=%s err=%s", wechat_user_id, exc)
    await db.commit()
    return sent


async def list_pending_for_account(
    db: AsyncSession, account_id: uuid.UUID
) -> list[WechatOutbox]:
    rows = (
        await db.execute(
            select(WechatOutbox)
            .where(
                WechatOutbox.account_id == account_id,
                WechatOutbox.status == "pending",
            )
            .order_by(WechatOutbox.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return list(rows)


__all__ = ("queue", "flush_for_user", "list_pending_for_account")
