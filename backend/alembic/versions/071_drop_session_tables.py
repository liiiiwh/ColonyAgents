"""drop sessions / session_branches / branch_agent_memories + 退役 FK 列 (ADR-018 step5/X 终局)

mission-only 终态：会话身份 = Mission(projects) + thread_key 字符串。所有 session/branch 容器
及指向它们的 FK 列全部退役。

- 删表：branch_agent_memories、session_branches、sessions（CASCADE 清掉残留 FK 约束）
- 删列：messages.session_id/branch_id、pending_approvals.session_id/branch_id、
  agents... agent_protocol_proposals.proposer_session_id、project_escalations.target_session_id、
  worker_invocation_log.thread_branch_id
- 加列：pending_approvals.thread_key
- builder_work_claims/builder_work_logs.session_id：FK 约束随 sessions DROP CASCADE 自动去除，列保留作历史审计

Revision ID: 071_drop_session_tables
Revises: 070_messages_keys_nullable
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "071_drop_session_tables"
down_revision: str | None = "070_messages_keys_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) 退役 FK 列（drop column 自动连带 PG 的 index + FK 约束）
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS session_id")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS branch_id")
    op.execute("ALTER TABLE pending_approvals DROP COLUMN IF EXISTS session_id")
    op.execute("ALTER TABLE pending_approvals DROP COLUMN IF EXISTS branch_id")
    op.execute("ALTER TABLE agent_protocol_proposals DROP COLUMN IF EXISTS proposer_session_id")
    op.execute("ALTER TABLE project_escalations DROP COLUMN IF EXISTS target_session_id")
    op.execute("ALTER TABLE worker_invocation_log DROP COLUMN IF EXISTS thread_branch_id")

    # 2) pending_approvals 加 thread_key
    op.add_column(
        "pending_approvals", sa.Column("thread_key", sa.String(length=96), nullable=True)
    )

    # 3) 删表（CASCADE：连带 builder_work_*.session_id 等残留 FK 约束一并去除；列保留）
    op.execute("DROP TABLE IF EXISTS branch_agent_memories CASCADE")
    op.execute("DROP TABLE IF EXISTS session_branches CASCADE")
    op.execute("DROP TABLE IF EXISTS sessions CASCADE")


def downgrade() -> None:
    # 终局删除不可逆（重建空表壳，不恢复数据 / 不恢复 FK 列）。仅为链式完整性提供占位。
    raise NotImplementedError(
        "ADR-018 step5/X 删表为终局操作，不支持 downgrade（mission-only 后无 session/branch 概念）。"
    )
