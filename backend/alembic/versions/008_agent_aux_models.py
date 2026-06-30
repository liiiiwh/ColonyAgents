"""agent_aux_models

Revision ID: 008_agent_aux_models
Revises: 007_knowledge
Create Date: 2026-04-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008_agent_aux_models"
down_revision: str | None = "007_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_aux_models",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="custom"),
        sa.Column("alias", sa.String(length=64), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["llm_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "model_id"),
    )
    op.create_index(
        "ix_agent_aux_models_agent_id", "agent_aux_models", ["agent_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_aux_models_agent_id", table_name="agent_aux_models")
    op.drop_table("agent_aux_models")
