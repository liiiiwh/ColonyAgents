"""M3: project_agent_memory table (per-project Agent memory)

Revision ID: 022_project_agent_memory
Revises: 021_project_schedule
Create Date: 2026-05-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "022_project_agent_memory"
down_revision: str | None = "021_project_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_agent_memory" in set(inspector.get_table_names()):
        return
    op.create_table(
        "project_agent_memory",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "project_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_node_name", sa.String(length=64), nullable=False),
        sa.Column("memory_md", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "compressed_message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("s3_key", sa.String(length=512), nullable=True),
        sa.Column(
            "last_compressed_at", sa.DateTime(timezone=True), nullable=True
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
        sa.UniqueConstraint(
            "project_id", "agent_node_name", name="uq_project_agent_memory"
        ),
    )
    op.create_index(
        "ix_project_agent_memory_project_id",
        "project_agent_memory",
        ["project_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_agent_memory" not in set(inspector.get_table_names()):
        return
    try:
        op.drop_index(
            "ix_project_agent_memory_project_id",
            table_name="project_agent_memory",
        )
    except Exception:
        pass
    op.drop_table("project_agent_memory")
