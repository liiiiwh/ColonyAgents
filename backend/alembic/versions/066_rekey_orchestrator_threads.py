"""re-key orchestrator messages off 'main' (ADR-018 Phase D)

Phase D stops collapsing distinct thread_ids to 'main'. Existing orchestrator (builder-chat)
messages were dual-written/backfilled as thread_key='main', colliding across builds. Re-key them
to their branch's unique thread_id so each build conversation is its own thread.

DELIBERATELY scoped to sessions.scope='orchestrator' — daemon/super main streams stay 'main'
(they are the one canonical 'main' per mission), sidestepping any legacy NULL-thread_kind daemon
main rows. ThreadAgentMemory is NOT re-keyed here: the read seam falls back to branch memory when
the thread row is absent, and the dual-write mirror re-creates it under the new key on next write.

Revision ID: 066_rekey_orchestrator_threads
Revises: 065_thread_agent_memory
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "066_rekey_orchestrator_threads"
down_revision: str | None = "065_thread_agent_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE messages m SET thread_key = b.thread_id
          FROM session_branches b
          JOIN sessions s ON s.id = b.session_id
         WHERE m.branch_id = b.id
           AND m.thread_key = 'main'
           AND s.scope = 'orchestrator'
           AND b.thread_id IS NOT NULL AND b.thread_id <> ''
        """
    )


def downgrade() -> None:
    # Best-effort inverse: orchestrator messages back to 'main'.
    op.execute(
        """
        UPDATE messages m SET thread_key = 'main'
          FROM session_branches b
          JOIN sessions s ON s.id = b.session_id
         WHERE m.branch_id = b.id
           AND s.scope = 'orchestrator'
           AND m.thread_key = b.thread_id
        """
    )
