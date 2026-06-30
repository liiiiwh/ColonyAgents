"""ADR-023 S7 · 知识库 per-super：加 super_agent_id + 从 mission.supervisor_agent_id 回填。

per-super 共享 KB：同一 super 的所有 mission 共用一份。新逻辑按 super_agent_id 取/建。

Revision ID: 075_kb_per_super
Revises: 074_drop_materials
"""
from __future__ import annotations

from alembic import op

revision: str = "075_kb_per_super"
down_revision: str | None = "074_drop_materials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS super_agent_id UUID "
        "REFERENCES agents(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_bases_super_agent_id "
        "ON knowledge_bases(super_agent_id)"
    )
    # 回填：从该 KB 原绑定 mission 的 supervisor_agent_id 取 super
    op.execute(
        "UPDATE knowledge_bases kb SET super_agent_id = m.supervisor_agent_id "
        "FROM missions m WHERE kb.mission_id = m.id AND kb.super_agent_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_bases_super_agent_id")
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS super_agent_id")
