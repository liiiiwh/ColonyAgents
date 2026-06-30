"""branch workspace OCC + compression failure tracking

Revision ID: 027_branch_workspace_version
Revises: 026_session_scope_daemon
Create Date: 2026-05-20

新增列到 session_branches：
- workspace_version: int NOT NULL DEFAULT 0 — 乐观并发控制版本号（C2）
- compression_disabled: bool NOT NULL DEFAULT false — 连续失败后停压缩（C4）
- last_compression_error: text NULL
- compression_consecutive_failures: int NOT NULL DEFAULT 0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "027_branch_workspace_version"
down_revision: str | None = "026_session_scope_daemon"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_branches",
        sa.Column(
            "workspace_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "session_branches",
        sa.Column(
            "compression_disabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "session_branches",
        sa.Column("last_compression_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "session_branches",
        sa.Column(
            "compression_consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("session_branches", "compression_consecutive_failures")
    op.drop_column("session_branches", "last_compression_error")
    op.drop_column("session_branches", "compression_disabled")
    op.drop_column("session_branches", "workspace_version")
