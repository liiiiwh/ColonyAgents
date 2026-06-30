"""agents.produces_deliverable

Revision ID: 009_agent_deliverable_flag
Revises: 008_agent_aux_models
Create Date: 2026-04-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009_agent_deliverable_flag"
down_revision: str | None = "008_agent_aux_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "produces_deliverable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "produces_deliverable")
