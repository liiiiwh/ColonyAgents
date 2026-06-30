"""providers: llm_providers + llm_models

Revision ID: 002_providers
Revises: 001_initial
Create Date: 2026-04-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_providers"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("api_key", sa.String(length=2048), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("extra_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("name", name="uq_llm_providers_name"),
    )
    op.create_index("ix_llm_providers_name", "llm_providers", ["name"])

    op.create_table(
        "llm_models",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("model_type", sa.String(length=16), nullable=False, server_default="chat"),
        sa.Column("context_window", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("supports_vision", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "supports_function_calling",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["llm_providers.id"],
            name="fk_llm_models_provider",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("provider_id", "model_id", name="uq_model_per_provider"),
    )
    op.create_index("ix_llm_models_provider_id", "llm_models", ["provider_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_models_provider_id", table_name="llm_models")
    op.drop_table("llm_models")
    op.drop_index("ix_llm_providers_name", table_name="llm_providers")
    op.drop_table("llm_providers")
