"""WeChat outbox：积压推送（首次推送失败 / token 临时无效）

Revision ID: 031_wechat_outbox
Revises: 030_wechat_approvals
Create Date: 2026-05-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "031_wechat_outbox"
down_revision: str | None = "030_wechat_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wechat_outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("target_wechat_id", sa.String(length=128), nullable=False),
        # notification | approval_resend
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="notification"),
        sa.Column("content", sa.Text(), nullable=False),
        # pending / sent / cancelled
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["wechat_clawbot_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wechat_outbox_pending",
        "wechat_outbox",
        ["account_id", "target_wechat_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_wechat_outbox_pending", table_name="wechat_outbox")
    op.drop_table("wechat_outbox")
