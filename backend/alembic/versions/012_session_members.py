"""session_members: 会话成员表支持多用户协作

若历史环境已存在该表，则跳过，避免重复建表失败。

Revision ID: 012_session_members
Revises: 011_workspace_jsonb
Create Date: 2026-04-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012_session_members"
down_revision: str | None = "011_workspace_jsonb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "session_members" in inspector.get_table_names():
        return

    op.create_table(
        "session_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, default="member"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("session_id", "user_id", name="uq_session_user_membership"),
    )

    op.create_index("ix_session_members_session_id", "session_members", ["session_id"])
    op.create_index("ix_session_members_user_id", "session_members", ["user_id"])

    op.execute(
        """
        INSERT INTO session_members (id, session_id, user_id, role, created_at, updated_at)
        SELECT gen_random_uuid(), id, user_id, 'owner', created_at, updated_at
        FROM sessions
        WHERE user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "session_members" not in inspector.get_table_names():
        return

    op.drop_index("ix_session_members_user_id", table_name="session_members")
    op.drop_index("ix_session_members_session_id", table_name="session_members")
    op.drop_table("session_members")