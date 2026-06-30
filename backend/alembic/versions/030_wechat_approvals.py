"""WeChat Clawbot 审批渠道 + pending_approvals 一等公民表

Revision ID: 030_wechat_approvals
Revises: 029_session_target_project
Create Date: 2026-05-20

新增三张表：
- wechat_clawbot_accounts：一个机器人账号（bot_token + base_url + ilink_bot_id + reviewers），
  跨项目共享；扫码登录后凭证落库。
- project_approval_channels：项目 ↔ clawbot 账号 + 项目专属审批人，1:1。
- pending_approvals：待审批请求一等公民。每次 request_approval 写一行；用户/微信回复后更新。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "030_wechat_approvals"
down_revision: str | None = "029_session_target_project"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── wechat_clawbot_accounts ───────────────────────────
    op.create_table(
        "wechat_clawbot_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False, server_default=""),
        # fernet 加密后的 bot_token；以 base_url + ilink_bot_id 唯一识别 bot 账号
        sa.Column("bot_token", sa.String(length=2048), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("ilink_bot_id", sa.String(length=128), nullable=False),
        sa.Column("ilink_user_id", sa.String(length=128), nullable=True),
        # 长轮询同步游标（base64）；服务端用它判断从哪条消息开始返回
        sa.Column("sync_buffer", sa.Text(), nullable=False, server_default=""),
        # per-user context_token 缓存（{user_id: token}）；回复时必带
        sa.Column("context_tokens", sa.JSON(), nullable=False, server_default="{}"),
        # 该 bot 账号下的默认审批人列表（WeChat user_id 字符串数组）
        # 项目级 reviewer 可在 project_approval_channels 单独配
        sa.Column("reviewers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # ─── project_approval_channels ─────────────────────────
    op.create_table(
        "project_approval_channels",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("clawbot_account_id", sa.UUID(), nullable=True),
        # 该 project 的审批人 wechat user_id 列表；空则用 clawbot_account.reviewers
        sa.Column("reviewer_wechat_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["clawbot_account_id"], ["wechat_clawbot_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("project_id"),
    )

    # ─── pending_approvals ─────────────────────────────────
    op.create_table(
        "pending_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        # 业务 ID（短串），给 LLM + 微信用户复用；全局唯一
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("branch_id", sa.UUID(), nullable=True),
        sa.Column("agent_node_name", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False, server_default="[]"),
        # pending / decided / expired / cancelled
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("decided_option", sa.String(length=256), nullable=True),
        # 'observe' | 'wechat:<user_id>' | 'auto'
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        # 微信分发追踪：发到哪个 bot / 哪些 user / 何时发出
        sa.Column("clawbot_account_id", sa.UUID(), nullable=True),
        sa.Column("clawbot_user_ids", sa.JSON(), nullable=True),
        sa.Column("clawbot_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["branch_id"], ["session_branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["clawbot_account_id"], ["wechat_clawbot_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_pending_approvals_project_id", "pending_approvals", ["project_id"])
    op.create_index("ix_pending_approvals_status", "pending_approvals", ["status"])
    op.create_index("ix_pending_approvals_request_id", "pending_approvals", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_pending_approvals_request_id", table_name="pending_approvals")
    op.drop_index("ix_pending_approvals_status", table_name="pending_approvals")
    op.drop_index("ix_pending_approvals_project_id", table_name="pending_approvals")
    op.drop_table("pending_approvals")
    op.drop_table("project_approval_channels")
    op.drop_table("wechat_clawbot_accounts")
