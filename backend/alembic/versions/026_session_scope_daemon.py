"""session scope enum 加 'daemon'（注释式 migration；string 列无需 DB 改动）

Revision ID: 026_session_scope_daemon
Revises: 025_branch_compression_marker
Create Date: 2026-05-20

Session.scope 是 VARCHAR(24) 不是 enum 类型，所以加新值 'daemon' 无需 schema 改动；
本 migration 只做幂等占位 + 自动建 builder 项目的 daemon scope session（如不存在）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "026_session_scope_daemon"
down_revision: str | None = "025_branch_compression_marker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 没有 schema 改动；仅作为版本占位
    # daemon session 由 project_daemon._ensure_daemon_branch 按需懒创建
    op.execute(sa.text("SELECT 1"))


def downgrade() -> None:
    op.execute(sa.text("SELECT 1"))
