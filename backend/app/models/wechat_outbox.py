"""微信推送 outbox：失败的消息暂存，等用户首次主动发消息后由 poller flush。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WechatOutbox(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "wechat_outbox"

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wechat_clawbot_accounts.id", ondelete="CASCADE"), nullable=False
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=True
    )
    target_wechat_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # notification | approval_resend
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="notification")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # pending / sent / cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
