"""materials: 物料库（id + key + title + value(JSONB)）

Revision ID: 016_materials
Revises: 015_agent_max_output_tokens
Create Date: 2026-04-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "016_materials"
down_revision: str | None = "015_agent_max_output_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = (
        postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
    )

    op.create_table(
        "materials",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("value", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_materials_key", "materials", ["key"])

    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_materials_value_gin "
            "ON materials USING gin (value)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_materials_value_gin")
    op.drop_index("ix_materials_key", table_name="materials")
    op.drop_table("materials")
