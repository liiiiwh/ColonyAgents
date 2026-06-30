"""thread_agent_memories (ADR-018 Phase B · compression memory rekey)

The (mission_id, thread_key) successor to branch_agent_memories(branch_id). Created + backfilled
from the existing branch/session graph; branch_agent_memories stays authoritative until the
compression subsystem's reads switch in a later Phase-B slice.

Revision ID: 065_thread_agent_memory
Revises: 064_agent_built_by_mission
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "065_thread_agent_memory"
down_revision: str | None = "064_agent_built_by_mission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "thread_agent_memories",
        sa.Column("id", sa.CHAR(32), primary_key=True),
        sa.Column("mission_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("thread_key", sa.String(length=96), nullable=False),
        sa.Column("agent_node_name", sa.String(length=64), nullable=False),
        sa.Column("memory_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("compressed_message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("s3_key", sa.String(length=512), nullable=True),
        sa.Column("last_compressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("mission_id", "thread_key", "agent_node_name", name="uq_thread_agent_memory"),
    )
    op.create_index("ix_thread_agent_memories_mission_id", "thread_agent_memories", ["mission_id"])
    op.create_index("ix_thread_agent_memories_thread_key", "thread_agent_memories", ["thread_key"])

    # Backfill from branch_agent_memories via the branch/session graph (same thread_key derivation
    # as messages: worker_health→'health'; super_worker_thread→branch.thread_id; else 'main').
    op.execute(
        """
        INSERT INTO thread_agent_memories
            (id, mission_id, thread_key, agent_node_name, memory_md,
             compressed_message_count, s3_key, last_compressed_at, created_at, updated_at)
        SELECT replace(gen_random_uuid()::text, '-', ''),
               s.project_id,
               CASE
                 WHEN b.thread_kind = 'worker_health' THEN 'health'
                 WHEN b.thread_kind = 'super_worker_thread' THEN b.thread_id
                 ELSE 'main'
               END,
               m.agent_node_name, m.memory_md, m.compressed_message_count,
               m.s3_key, m.last_compressed_at, now(), now()
          FROM branch_agent_memories m
          JOIN session_branches b ON b.id = m.branch_id
          JOIN sessions s ON s.id = b.session_id
        ON CONFLICT (mission_id, thread_key, agent_node_name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_thread_agent_memories_thread_key", table_name="thread_agent_memories")
    op.drop_index("ix_thread_agent_memories_mission_id", table_name="thread_agent_memories")
    op.drop_table("thread_agent_memories")
