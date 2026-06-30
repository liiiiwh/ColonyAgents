"""wechat_outbox.sent_at → TIMESTAMP WITH TIME ZONE

Revision ID: 034_wechat_outbox_sent_at_tz
Revises: 033_branch_task_group
Create Date: 2026-05-22

ORM 把 `sent_at` 标成 `Mapped[datetime | None]`（无 timezone），SQLAlchemy 推断为
`TIMESTAMP WITHOUT TIME ZONE`。但 wechat_outbox.flush() 写入 `datetime.now(UTC)`
（offset-aware）→ asyncpg `timestamp_encode` 抛 `TypeError: can't subtract offset-naive
and offset-aware datetimes`，整个 outbox flush 失败，wechat_intent 也连锁失败（用户回复
审批意见被吞）。

修正为 `TIMESTAMP WITH TIME ZONE`；PostgreSQL 内部统一存 UTC。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "034_wechat_outbox_sent_at_tz"
down_revision: str | None = "033_branch_task_group"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "wechat_outbox",
        "sent_at",
        existing_type=sa.TIMESTAMP(timezone=False),
        type_=sa.TIMESTAMP(timezone=True),
        existing_nullable=True,
        postgresql_using="sent_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    op.alter_column(
        "wechat_outbox",
        "sent_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        type_=sa.TIMESTAMP(timezone=False),
        existing_nullable=True,
        postgresql_using="sent_at AT TIME ZONE 'UTC'",
    )
