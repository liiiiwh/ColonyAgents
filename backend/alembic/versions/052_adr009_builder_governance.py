"""ADR-009 · builder_work_claims（G4 多 session 互斥锁）+ builder_work_logs（G5 工作记录）。"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "052_adr009_builder_governance"
down_revision = "051_adr008_routing_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "builder_work_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(128), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_builder_work_claims_key", "builder_work_claims", ["key"], unique=True)

    op.create_table(
        "builder_work_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("affected_supers", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("result", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_builder_work_logs_session_id", "builder_work_logs", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_builder_work_logs_session_id", table_name="builder_work_logs")
    op.drop_table("builder_work_logs")
    op.drop_index("ix_builder_work_claims_key", table_name="builder_work_claims")
    op.drop_table("builder_work_claims")
