"""SessionBranch.task_group —— daemon task-based branching

Revision ID: 033_branch_task_group
Revises: 032_mcp_startup_command
Create Date: 2026-05-22

Daemon 由「每次 run_once 新建 branch」改为「按 task_group 聚合」：
- 同 session 内 task_group 相同 + is_current=True → 复用该 branch（同一天的 cron / interval 聚到 1 行）
- 跨天 / 业务范围切换（task_group 变化）→ 新建 branch
- 显式不传 task_group：manual trigger → 'manual-<ts>'；schedule trigger → 'sched-<id>-<date>'

nullable：兼容老数据；查询用 (session_id, task_group) 复合索引加速。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "033_branch_task_group"
down_revision: str | None = "032_mcp_startup_command"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_branches",
        sa.Column("task_group", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_session_branches_session_id_task_group",
        "session_branches",
        ["session_id", "task_group"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_session_branches_session_id_task_group", table_name="session_branches"
    )
    op.drop_column("session_branches", "task_group")
