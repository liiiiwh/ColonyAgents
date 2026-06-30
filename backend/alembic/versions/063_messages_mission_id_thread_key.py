"""messages.mission_id + thread_key (ADR-018 step 2 · dual-write/backfill)

Target keying for the Mission-only model. Nullable + backfilled from the existing
branch/session graph; session_id/branch_id stay for now (drop in step 5).

  thread_key: worker_health → 'health'; super_worker_thread → branch.thread_id; else 'main'.
  mission_id: the message's session.project_id.

Revision ID: 063_msg_mission_thread_key
Revises: 062_agent_model_id_nullable
Create Date: 2026-06-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "063_msg_mission_thread_key"
down_revision: str | None = "062_agent_model_id_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("mission_id", sa.dialects.postgresql.UUID(), nullable=True))
    op.add_column("messages", sa.Column("thread_key", sa.String(length=96), nullable=True))
    op.create_index("ix_messages_mission_id", "messages", ["mission_id"])
    op.create_index("ix_messages_thread_key", "messages", ["thread_key"])
    op.create_foreign_key(
        "fk_messages_mission_id", "messages", "projects", ["mission_id"], ["id"], ondelete="CASCADE"
    )
    # Backfill from the existing branch/session graph.
    op.execute(
        """
        UPDATE messages m SET
          mission_id = s.project_id,
          thread_key = CASE
            WHEN b.thread_kind = 'worker_health' THEN 'health'
            WHEN b.thread_kind = 'super_worker_thread' THEN b.thread_id
            ELSE 'main'
          END
        FROM session_branches b, sessions s
        WHERE m.branch_id = b.id AND m.session_id = s.id
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_messages_mission_id", "messages", type_="foreignkey")
    op.drop_index("ix_messages_thread_key", table_name="messages")
    op.drop_index("ix_messages_mission_id", table_name="messages")
    op.drop_column("messages", "thread_key")
    op.drop_column("messages", "mission_id")
