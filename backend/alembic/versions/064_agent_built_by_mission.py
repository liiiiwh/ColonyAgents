"""agents.built_by_mission_id (ADR-018 D3 · 1:1 super provenance)

A produced super records the origin Builder mission so super self-iteration can route back
to where it was designed, replacing session.target_project_id. Nullable; write-only during the
migration window (escalation routing switches to it in step 5).

Revision ID: 064_agent_built_by_mission
Revises: 063_msg_mission_thread_key
Create Date: 2026-06-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "064_agent_built_by_mission"
down_revision: str | None = "063_msg_mission_thread_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents", sa.Column("built_by_mission_id", sa.dialects.postgresql.UUID(), nullable=True)
    )
    op.create_index("ix_agents_built_by_mission_id", "agents", ["built_by_mission_id"])
    op.create_foreign_key(
        "fk_agents_built_by_mission_id", "agents", "projects",
        ["built_by_mission_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_agents_built_by_mission_id", "agents", type_="foreignkey")
    op.drop_index("ix_agents_built_by_mission_id", table_name="agents")
    op.drop_column("agents", "built_by_mission_id")
