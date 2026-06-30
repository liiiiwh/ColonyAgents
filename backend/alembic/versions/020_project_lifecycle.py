"""M1: project lifecycle — runtime_status column + project_run_state table

- 给 projects 加 runtime_status 列（默认 'stopped'）+ 索引
- 新建 project_run_state 表（每 project 至多一行）

Revision ID: 020_project_lifecycle
Revises: 019_colony_baseline
Create Date: 2026-05-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "020_project_lifecycle"
down_revision: str | None = "019_colony_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1) projects.runtime_status ──
    project_cols = {col["name"] for col in inspector.get_columns("projects")}
    if "runtime_status" not in project_cols:
        op.add_column(
            "projects",
            sa.Column(
                "runtime_status",
                sa.String(length=16),
                nullable=False,
                server_default="stopped",
            ),
        )
        op.create_index(
            "ix_projects_runtime_status", "projects", ["runtime_status"]
        )

    # ── 2) project_run_state ──
    if "project_run_state" not in set(inspector.get_table_names()):
        op.create_table(
            "project_run_state",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column(
                "project_id",
                sa.UUID(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="stopped",
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "last_heartbeat_at", sa.DateTime(timezone=True), nullable=True
            ),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("current_step", sa.String(length=64), nullable=True),
            sa.Column(
                "run_count", sa.Integer(), nullable=False, server_default="0"
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
                "project_id", name="uq_project_run_state_project"
            ),
        )
        op.create_index(
            "ix_project_run_state_project_id",
            "project_run_state",
            ["project_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "project_run_state" in set(inspector.get_table_names()):
        try:
            op.drop_index(
                "ix_project_run_state_project_id", table_name="project_run_state"
            )
        except Exception:
            pass
        op.drop_table("project_run_state")

    project_cols = {col["name"] for col in inspector.get_columns("projects")}
    if "runtime_status" in project_cols:
        try:
            op.drop_index("ix_projects_runtime_status", table_name="projects")
        except Exception:
            pass
        op.drop_column("projects", "runtime_status")
