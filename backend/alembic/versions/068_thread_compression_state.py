"""thread_compression_state (ADR-018 step5/K · 压缩状态 → Mission/Thread)

把挂在 SessionBranch 上的压缩状态（compression_in_progress / compressed_up_to_at /
compression_disabled / consecutive_failures / last_error / thread 级 compression_config）
搬到 (mission_id, thread_key) 小表。

回填：从有压缩痕迹的 session_branch 派生 (project_id, thread_key) 建行。同一 thread_key
多条 branch 取水位线最晚的一条（DISTINCT ON）。SessionBranch 的压缩列暂留（Slice X drop）。

Revision ID: 068_thread_compression_state
Revises: 067_mission_workspace
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "068_thread_compression_state"
down_revision: str | None = "067_mission_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "thread_compression_state",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("mission_id", postgresql.UUID(), nullable=False),
        sa.Column("thread_key", sa.String(length=96), nullable=False),
        sa.Column("compression_config", postgresql.JSONB(), nullable=True),
        sa.Column(
            "compression_disabled", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("last_compression_error", sa.Text(), nullable=True),
        sa.Column(
            "compression_consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "compression_in_progress", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("compressed_up_to_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["mission_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id", "thread_key", name="uq_thread_compression_state"),
    )
    op.create_index(
        "ix_thread_compression_state_mission_id", "thread_compression_state", ["mission_id"]
    )
    op.create_index(
        "ix_thread_compression_state_thread_key", "thread_compression_state", ["thread_key"]
    )
    # 回填：从有压缩痕迹的 branch 派生 (project_id, thread_key) 行（同 thread_key 取水位线最晚）
    op.execute(
        """
        INSERT INTO thread_compression_state (
            id, mission_id, thread_key, compression_config, compression_disabled,
            last_compression_error, compression_consecutive_failures,
            compression_in_progress, compressed_up_to_at, created_at, updated_at
        )
        SELECT DISTINCT ON (s.project_id, tk.thread_key)
            gen_random_uuid(), s.project_id, tk.thread_key,
            b.compression_config, b.compression_disabled,
            b.last_compression_error, b.compression_consecutive_failures,
            false, b.compressed_up_to_at, now(), now()
        FROM session_branches b
        JOIN sessions s ON s.id = b.session_id
        CROSS JOIN LATERAL (
            SELECT CASE
                WHEN b.thread_kind='super_main_runtime' THEN 'main'
                WHEN b.thread_kind='worker_health' THEN 'health'
                ELSE b.thread_id
            END AS thread_key
        ) tk
        WHERE b.compressed_up_to_at IS NOT NULL
           OR b.compression_disabled
           OR b.compression_consecutive_failures > 0
           OR b.compression_config IS NOT NULL
        ORDER BY s.project_id, tk.thread_key, b.compressed_up_to_at DESC NULLS LAST
        ON CONFLICT (mission_id, thread_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_thread_compression_state_thread_key", table_name="thread_compression_state"
    )
    op.drop_index(
        "ix_thread_compression_state_mission_id", table_name="thread_compression_state"
    )
    op.drop_table("thread_compression_state")
