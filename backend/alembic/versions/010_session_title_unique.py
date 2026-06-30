"""sessions 表：同 (project_id, user_id) 下 title 唯一

先 dedupe 历史重复 title（给重复记录追加 " (N)" 后缀），再建立部分唯一索引。
使用 WHERE title IS NOT NULL 的部分索引，允许多条 title=NULL。

Revision ID: 010_session_title_unique
Revises: 009_agent_deliverable_flag
Create Date: 2026-04-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010_session_title_unique"
down_revision: str | None = "009_agent_deliverable_flag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. 找出 (project_id, user_id, title) 重复的行，给重复项追加 " (N)" 后缀
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   title,
                   ROW_NUMBER() OVER (
                       PARTITION BY project_id, user_id, title
                       ORDER BY created_at
                   ) AS rn
            FROM sessions
            WHERE title IS NOT NULL
        )
        UPDATE sessions s
        SET title = s.title || ' (' || r.rn || ')'
        FROM ranked r
        WHERE r.id = s.id AND r.rn > 1
        """
    )

    # 2. 创建部分唯一索引（title 非空时唯一）
    op.create_index(
        "uq_sessions_title_per_owner",
        "sessions",
        ["project_id", "user_id", "title"],
        unique=True,
        postgresql_where=sa.text("title IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_sessions_title_per_owner", table_name="sessions")
