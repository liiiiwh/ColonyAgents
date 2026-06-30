"""ADR-010 R3 · shell_audit_log（run_shell 不可变审计）

Revision ID: 055_shell_audit_log
Revises: 054_widen_current_step
Create Date: 2026-06-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "055_shell_audit_log"
down_revision = "054_widen_current_step"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shell_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("layer", sa.String(length=32), nullable=True),
        sa.Column("rule", sa.String(length=64), nullable=True),
        sa.Column("gate_reason", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("stderr", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index("ix_shell_audit_log_actor", "shell_audit_log", ["actor"])


def downgrade() -> None:
    op.drop_index("ix_shell_audit_log_actor", table_name="shell_audit_log")
    op.drop_table("shell_audit_log")
