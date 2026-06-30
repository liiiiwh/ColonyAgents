"""projects + project_nodes

Revision ID: 005_projects
Revises: 004_agents
Create Date: 2026-04-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_projects"
down_revision: str | None = "004_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("supervisor_agent_id", sa.Uuid(), nullable=False),
        sa.Column("auto_approve", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "context_compression_threshold", sa.Integer(), nullable=False, server_default="4000"
        ),
        sa.Column("workflow_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["supervisor_agent_id"], ["agents.id"], name="fk_projects_supervisor", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_projects_user", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
    )
    op.create_index("ix_projects_slug", "projects", ["slug"])

    op.create_table(
        "project_nodes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("node_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("node_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "node_name", name="uq_node_name_per_project"),
    )
    op.create_index("ix_project_nodes_project_id", "project_nodes", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_nodes_project_id", table_name="project_nodes")
    op.drop_table("project_nodes")
    op.drop_index("ix_projects_slug", table_name="projects")
    op.drop_table("projects")
