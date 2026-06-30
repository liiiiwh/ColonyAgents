"""messages.session_id / branch_id → nullable (ADR-018 step5/H)

append_message 改成按 (mission_id, thread_key) 写消息，不再依赖 branch/session 行（thread 解析缝
消失，thread_key 由纯函数算出）。旧的 session_id/branch_id 列先放开 NOT NULL，新写入留 NULL；
Slice X 随 sessions/session_branches 表一起 drop。

Revision ID: 070_messages_keys_nullable
Revises: 069_rekey_thread_memory
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "070_messages_keys_nullable"
down_revision: str | None = "069_rekey_thread_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("messages", "session_id", nullable=True)
    op.alter_column("messages", "branch_id", nullable=True)


def downgrade() -> None:
    # 反向：要求列重新 NOT NULL（仅在无 NULL 行时可行；H 之后的新消息会有 NULL，故 downgrade
    # 前需先回填或清理——这里只声明意图，不自动回填）。
    op.alter_column("messages", "branch_id", nullable=False)
    op.alter_column("messages", "session_id", nullable=False)
