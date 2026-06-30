"""branch compression marker + in-progress flag (异步压缩防并发)

Revision ID: 025_branch_compression_marker
Revises: 024_remote_skill_install
Create Date: 2026-05-19

新增两列到 `session_branches`：
- `compression_in_progress` BOOLEAN NOT NULL DEFAULT FALSE
- `compressed_up_to_at` TIMESTAMPTZ NULL

支持 maybe_compress_context 异步化（fire-and-forget background task）+
单 branch 不并行压缩。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "025_branch_compression_marker"
down_revision: str | None = "024_remote_skill_install"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_branches",
        sa.Column(
            "compression_in_progress",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "session_branches",
        sa.Column(
            "compressed_up_to_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("session_branches", "compressed_up_to_at")
    op.drop_column("session_branches", "compression_in_progress")
