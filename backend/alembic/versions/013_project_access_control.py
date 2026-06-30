"""project access control: access_mode + project_user_access

Revision ID: 013_project_access_control
Revises: 012_session_members
Create Date: 2026-04-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "013_project_access_control"
down_revision: str | None = "012_session_members"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    project_columns = {column["name"] for column in inspector.get_columns("projects")}
    if "access_mode" not in project_columns:
        op.add_column(
            "projects",
            sa.Column(
                "access_mode",
                sa.String(length=16),
                nullable=False,
                server_default="public",
            ),
        )
        op.execute("UPDATE projects SET access_mode = 'public' WHERE access_mode IS NULL")
        op.alter_column("projects", "access_mode", server_default=None)

    if "project_user_access" not in inspector.get_table_names():
        op.create_table(
            "project_user_access",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
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
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("project_id", "user_id", name="uq_project_user_access"),
        )
        op.create_index(
            "ix_project_user_access_project_id",
            "project_user_access",
            ["project_id"],
        )
        op.create_index(
            "ix_project_user_access_user_id",
            "project_user_access",
            ["user_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "project_user_access" in inspector.get_table_names():
        op.drop_index("ix_project_user_access_user_id", table_name="project_user_access")
        op.drop_index("ix_project_user_access_project_id", table_name="project_user_access")
        op.drop_table("project_user_access")

    project_columns = {column["name"] for column in inspector.get_columns("projects")}
    if "access_mode" in project_columns:
        op.drop_column("projects", "access_mode")