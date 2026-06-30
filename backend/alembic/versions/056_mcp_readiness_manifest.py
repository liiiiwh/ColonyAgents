"""ADR-010 R1 · mcp_servers.readiness_manifest

Revision ID: 056_mcp_readiness_manifest
Revises: 055_shell_audit_log
Create Date: 2026-06-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "056_mcp_readiness_manifest"
down_revision = "055_shell_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("readiness_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "readiness_manifest")
