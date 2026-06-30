"""skills + mcp_servers

Revision ID: 003_skills_mcp
Revises: 002_providers
Create Date: 2026-04-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_skills_mcp"
down_revision: str | None = "002_providers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="0.1.0"),
        sa.Column("skill_type", sa.String(length=32), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("builtin_ref", sa.String(length=128), nullable=True),
        sa.Column("config_schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("slug", name="uq_skills_slug"),
    )
    op.create_index("ix_skills_name", "skills", ["name"])
    op.create_index("ix_skills_slug", "skills", ["slug"])

    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("server_type", sa.String(length=16), nullable=False),
        sa.Column("command", sa.JSON(), nullable=True),
        sa.Column("env_vars", sa.JSON(), nullable=True),
        sa.Column("url", sa.String(length=512), nullable=True),
        sa.Column("headers", sa.JSON(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("name", name="uq_mcp_servers_name"),
    )
    op.create_index("ix_mcp_servers_name", "mcp_servers", ["name"])


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_name", table_name="mcp_servers")
    op.drop_table("mcp_servers")
    op.drop_index("ix_skills_slug", table_name="skills")
    op.drop_index("ix_skills_name", table_name="skills")
    op.drop_table("skills")
