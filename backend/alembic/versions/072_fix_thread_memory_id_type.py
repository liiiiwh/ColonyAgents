"""fix thread_agent_memories.id CHAR(32) → uuid (ADR-018 · 065 建表 id 类型错)

迁移 065 把 thread_agent_memories.id 建成 CHAR(32)（回填用 replace(gen_random_uuid(),'-','')），
但 ORM UUIDPrimaryKeyMixin 用 Uuid 类型插 36 字符带连字符 UUID → 真 PG 上
StringDataRightTruncationError（压缩写 ThreadAgentMemory 失败）。sqlite 测试因 CHAR 宽松未暴露。
把列类型改成 uuid（已有 32-hex 值 PG 可直接 ::uuid 转）。

Revision ID: 072_fix_thread_memory_id_type
Revises: 071_drop_session_tables
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "072_fix_thread_memory_id_type"
down_revision: str | None = "071_drop_session_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE thread_agent_memories "
        "ALTER COLUMN id TYPE uuid USING id::uuid"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE thread_agent_memories "
        "ALTER COLUMN id TYPE char(32) USING replace(id::text, '-', '')"
    )
