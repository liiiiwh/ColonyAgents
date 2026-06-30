"""M2: project_schedule table (cron / interval / event triggers)

Revision ID: 021_project_schedule
Revises: 020_project_lifecycle
Create Date: 2026-05-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "021_project_schedule"
down_revision: str | None = "020_project_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_schedule" in set(inspector.get_table_names()):
        return
    op.create_table(
        "project_schedule",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "project_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("expr", sa.String(length=128), nullable=False),
        sa.Column(
            "payload_template", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "fire_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_by",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_project_schedule_project_id",
        "project_schedule",
        ["project_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_schedule" not in set(inspector.get_table_names()):
        return
    try:
        op.drop_index(
            "ix_project_schedule_project_id", table_name="project_schedule"
        )
    except Exception:
        pass
    op.drop_table("project_schedule")
