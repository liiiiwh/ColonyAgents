"""V7.4 · drop agent_activities（ADR-007 ActivityTree 退役）。

观测真相源改为 chat 消息（daemon V7.2 流式落消息）。agent_activities 表 + 树查询 + intervene-on-activity
全部退役。telemetry 切 worker_invocation_log。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "050_v7_drop_agent_activities"
down_revision = "049_v6_skill_scope_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_activities CASCADE")


def downgrade() -> None:
    # 回退：重建最小表结构（不恢复数据）
    op.create_table(
        "agent_activities",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("parent_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("super_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("result", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("cost_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_cents", sa.Integer(), nullable=True),
        sa.Column("channel", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
