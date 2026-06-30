"""ADR-011 R4a · sessions.relay_to_session_id

Revision ID: 057_session_relay
Revises: 056_mcp_readiness_manifest
Create Date: 2026-06-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "057_session_relay"
down_revision = "056_mcp_readiness_manifest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("relay_to_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_sessions_relay_to_session", "sessions", "sessions",
        ["relay_to_session_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_sessions_relay_to_session_id", "sessions", ["relay_to_session_id"])


def downgrade() -> None:
    op.drop_index("ix_sessions_relay_to_session_id", table_name="sessions")
    op.drop_constraint("fk_sessions_relay_to_session", "sessions", type_="foreignkey")
    op.drop_column("sessions", "relay_to_session_id")
