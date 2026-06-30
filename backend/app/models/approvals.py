"""微信 Clawbot 审批渠道 + pending_approvals 模型。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WechatClawbotAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """微信 Clawbot 机器人账号。一个账号 = 一个扫码登录的 bot；跨项目共享。"""

    __tablename__ = "wechat_clawbot_accounts"

    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    bot_token: Mapped[str] = mapped_column(String(2048), nullable=False)  # fernet encrypted
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    ilink_bot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ilink_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sync_buffer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_tokens: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # ADR-008 P4 · WeChat Router 粘性路由缓存：{wechat_user_id: 上次路由到的 target id}
    # 连续自由消息粘同一 super session，直到用户显式切换。
    routing_cache: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # 该 bot 下默认审批人 WeChat user_id 列表（'user@im.wechat' 形式）
    reviewers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class MissionApprovalChannel(Base, TimestampMixin):
    """项目 → clawbot 账号 + 项目专属审批人配置。1 个 project ≤ 1 条配置。"""

    __tablename__ = "mission_approval_channels"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), primary_key=True
    )
    clawbot_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wechat_clawbot_accounts.id", ondelete="SET NULL"), nullable=True
    )
    # 项目专属审批人 WeChat user_id 列表；为空则使用 clawbot_account.reviewers
    reviewer_wechat_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PendingApproval(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """待审批请求一等公民。

    每次 supervisor 调 request_approval 时插一行；用户在 observe 页点 / 微信回复后更新 status。
    `request_id` 是给 LLM / 微信用户的短业务 ID（全局唯一）。
    """

    __tablename__ = "pending_approvals"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # ADR-018 mission-only · thread 标识（mission_id 即 mission_id；session_id/branch_id 退役）
    thread_key: Mapped[str | None] = mapped_column(String(96), nullable=True)
    agent_node_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # pending / decided / expired / cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    decided_option: Mapped[str | None] = mapped_column(String(256), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clawbot_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wechat_clawbot_accounts.id", ondelete="SET NULL"), nullable=True
    )
    clawbot_user_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    clawbot_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
