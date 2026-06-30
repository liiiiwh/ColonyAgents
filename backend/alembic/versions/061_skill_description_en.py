"""skills.description_en —— optional English description

Adds a nullable English description to skills. When both description (default/zh) and
description_en are non-empty, the admin list page shows the one matching the current UI
language; if description_en is empty it falls back to description.

Revision ID: 061_skill_description_en
Revises: 060_agent_thinking_level
Create Date: 2026-06-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "061_skill_description_en"
down_revision: str | None = "060_agent_thinking_level"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column("description_en", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("skills", "description_en")
