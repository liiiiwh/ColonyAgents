"""sessions + branches + messages + memories

Revision ID: 006_sessions
Revises: 005_projects
Create Date: 2026-04-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006_sessions"
down_revision: str | None = "005_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_sessions_project_id", "sessions", ["project_id"])

    op.create_table(
        "session_branches",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("parent_branch_id", sa.Uuid(), nullable=True),
        sa.Column("branch_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version_label", sa.String(length=64), nullable=False, server_default="v1"),
        sa.Column("description", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("workspace", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_branch_id"], ["session_branches.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_session_branches_session_id", "session_branches", ["session_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("is_compressed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["session_branches.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_index("ix_messages_branch_id", "messages", ["branch_id"])

    op.create_table(
        "branch_agent_memories",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("agent_node_name", sa.String(length=64), nullable=False),
        sa.Column("memory_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("compressed_message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("s3_key", sa.String(length=512), nullable=True),
        sa.Column("last_compressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["branch_id"], ["session_branches.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("branch_id", "agent_node_name", name="uq_memory_per_branch_agent"),
    )
    op.create_index(
        "ix_branch_memories_branch", "branch_agent_memories", ["branch_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_branch_memories_branch", table_name="branch_agent_memories")
    op.drop_table("branch_agent_memories")
    op.drop_index("ix_messages_branch_id", table_name="messages")
    op.drop_index("ix_messages_session_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_session_branches_session_id", table_name="session_branches")
    op.drop_table("session_branches")
    op.drop_index("ix_sessions_project_id", table_name="sessions")
    op.drop_table("sessions")
