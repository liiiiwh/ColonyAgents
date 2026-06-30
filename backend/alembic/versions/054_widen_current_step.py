"""widen project_run_state.current_step 64->255

paused_reason 等长文案写入 current_step 时 String(64) 溢出
（StringDataRightTruncationError: value too long for type character varying(64)），
放宽到 255；代码侧 _clip_step 再兜底裁剪。

Revision ID: 054_widen_current_step
Revises: 053_worker_health_category
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "054_widen_current_step"
down_revision = "053_worker_health_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "project_run_state",
        "current_step",
        existing_type=sa.String(length=64),
        type_=sa.String(length=255),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "project_run_state",
        "current_step",
        existing_type=sa.String(length=255),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
