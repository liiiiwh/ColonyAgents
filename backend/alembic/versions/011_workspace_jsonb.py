"""session_branches.workspace: JSON → JSONB（支持 jsonb_set 原子更新）

Revision ID: 011_workspace_jsonb
Revises: 010_session_title_unique
Create Date: 2026-04-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011_workspace_jsonb"
down_revision: str | None = "010_session_title_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # session_branches.workspace: JSON → JSONB
    op.execute(
        "ALTER TABLE session_branches "
        "ALTER COLUMN workspace TYPE JSONB USING workspace::jsonb"
    )
    # 顺便把 messages.meta、sessions.* 相关 JSON 也升级为 JSONB（不影响现有数据）
    # —— 只挑关键的那几张表，其他保持 JSON 以节省改动面
    op.execute("ALTER TABLE messages ALTER COLUMN meta TYPE JSONB USING meta::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE session_branches ALTER COLUMN workspace TYPE JSON USING workspace::json")
    op.execute("ALTER TABLE messages ALTER COLUMN meta TYPE JSON USING meta::json")
