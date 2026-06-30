"""projects.workspace + workspace_version (ADR-018 step5/W · workspace → Mission)

workflow 状态引擎（节点 status/state/artifacts/decision）从 SessionBranch 搬到 Mission(Project)。
一个 Mission 一份 workspace；workspace_version 走乐观并发 CAS。

回填：每个 project 取它名下 session 的某条 branch 的 workspace —— 优先
super_main_runtime（D 之后的 daemon 主流），否则取最近活跃且 workspace 非空的 branch。
SessionBranch.workspace 列暂留（Slice X 随表一起 drop）。

Revision ID: 067_mission_workspace
Revises: 066_rekey_orchestrator_threads
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "067_mission_workspace"
down_revision: str | None = "066_rekey_orchestrator_threads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("workspace", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "projects",
        sa.Column(
            "workspace_version", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    # 回填：每 project 选一条 branch 的 workspace（super_main_runtime 优先，再按 last_active_at）
    op.execute(
        """
        UPDATE projects p SET
          workspace = sub.workspace,
          workspace_version = sub.workspace_version
        FROM (
          SELECT DISTINCT ON (s.project_id)
            s.project_id, b.workspace, b.workspace_version
          FROM session_branches b
          JOIN sessions s ON b.session_id = s.id
          WHERE b.workspace IS NOT NULL AND b.workspace::text <> '{}'
          ORDER BY
            s.project_id,
            (b.thread_kind = 'super_main_runtime') DESC,
            b.last_active_at DESC
        ) sub
        WHERE p.id = sub.project_id
        """
    )


def downgrade() -> None:
    op.drop_column("projects", "workspace_version")
    op.drop_column("projects", "workspace")
