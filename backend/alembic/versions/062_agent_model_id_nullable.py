"""agents.model_id nullable —— platform agents bind the default model at runtime

Platform agents (Builder + workers) are now seeded at boot regardless of whether an LLM
is configured. A NULL model_id means "use the platform default model" (resolved at runtime
in build_agent_executor); when no default is configured the agent simply doesn't run.
This makes model_id nullable so agents can exist before any provider/model.

Revision ID: 062_agent_model_id_nullable
Revises: 061_skill_description_en
Create Date: 2026-06-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "062_agent_model_id_nullable"
down_revision: str | None = "061_skill_description_en"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("agents", "model_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)


def downgrade() -> None:
    # Rows with NULL model_id must be reassigned before re-tightening; left to the operator.
    op.alter_column("agents", "model_id", existing_type=sa.dialects.postgresql.UUID(), nullable=False)
