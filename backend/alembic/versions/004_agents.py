"""agents + agent_skills + agent_mcp_servers

Revision ID: 004_agents
Revises: 003_skills_mcp
Create Date: 2026-04-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_agents"
down_revision: str | None = "003_skills_mcp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("soul_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("protocol_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("domain_memory_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("max_iterations", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("extra_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["model_id"], ["llm_models.id"], name="fk_agents_model", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("name", name="uq_agents_name"),
    )
    op.create_index("ix_agents_name", "agents", ["name"])

    op.create_table(
        "agent_skills",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "skill_id"),
    )

    op.create_table(
        "agent_mcp_servers",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("mcp_server_id", sa.Uuid(), nullable=False),
        sa.Column("tool_filter", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mcp_server_id"], ["mcp_servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "mcp_server_id"),
    )


def downgrade() -> None:
    op.drop_table("agent_mcp_servers")
    op.drop_table("agent_skills")
    op.drop_index("ix_agents_name", table_name="agents")
    op.drop_table("agents")
