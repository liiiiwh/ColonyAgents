"""Session → target Project 绑定（一对多）

Revision ID: 029_session_target_project
Revises: 028_kb_project_link
Create Date: 2026-05-20

Builder Chat session 在创建 worker project 后，写一份反向指针到 target_project_id。
该 worker project 被删时 CASCADE 一起删掉对应 session，避免孤儿对话。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "029_session_target_project"
down_revision: str | None = "028_kb_project_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("target_project_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sessions_target_project",
        "sessions",
        "projects",
        ["target_project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_sessions_target_project_id",
        "sessions",
        ["target_project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_target_project_id", table_name="sessions")
    op.drop_constraint(
        "fk_sessions_target_project", "sessions", type_="foreignkey"
    )
    op.drop_column("sessions", "target_project_id")
