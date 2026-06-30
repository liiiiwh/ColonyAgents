"""re-key orchestrator thread_agent_memories off 'main' (ADR-018 step5/M)

065 把 branch 记忆回填进 thread_agent_memories 时，非规范线程（orchestrator/builder/legacy）
统一用了 thread_key='main'；但 Phase D（066）已把这些线程的 messages re-key 到各自 thread_id。
本迁移对 thread_agent_memories 做同样的 re-key，让记忆读（thread_key_for 派生）能命中。

与 066 对 messages 的逻辑一致：只动「能在 session_branches 里找到对应非规范 branch」的 'main' 行。
super_main_runtime / worker_health 的规范线程不动。

Revision ID: 069_rekey_thread_memory
Revises: 068_thread_compression_state
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "069_rekey_thread_memory"
down_revision: str | None = "068_thread_compression_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # orchestrator/builder/legacy 线程：thread_key 'main' → branch.thread_id（与 messages 对齐）。
    # ON CONFLICT 由 unique(mission_id, thread_key, agent_node_name) 守护：目标键已存在则跳过。
    op.execute(
        """
        UPDATE thread_agent_memories tam SET thread_key = b.thread_id
        FROM session_branches b
        JOIN sessions s ON s.id = b.session_id
        WHERE s.project_id = tam.mission_id
          AND tam.thread_key = 'main'
          AND b.thread_kind IS NOT NULL
          AND b.thread_kind NOT IN ('super_main_runtime', 'worker_health')
          AND b.thread_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM thread_agent_memories x
             WHERE x.mission_id = tam.mission_id
               AND x.thread_key = b.thread_id
               AND x.agent_node_name = tam.agent_node_name
          )
        """
    )


def downgrade() -> None:
    # 反向：把刚 re-key 到 thread_id 的非规范线程记忆收回 'main'（best-effort）。
    op.execute(
        """
        UPDATE thread_agent_memories tam SET thread_key = 'main'
        FROM session_branches b
        JOIN sessions s ON s.id = b.session_id
        WHERE s.project_id = tam.mission_id
          AND tam.thread_key = b.thread_id
          AND b.thread_kind IS NOT NULL
          AND b.thread_kind NOT IN ('super_main_runtime', 'worker_health')
          AND NOT EXISTS (
            SELECT 1 FROM thread_agent_memories x
             WHERE x.mission_id = tam.mission_id
               AND x.thread_key = 'main'
               AND x.agent_node_name = tam.agent_node_name
          )
        """
    )
