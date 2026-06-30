"""v6 · KnowledgeBase 加 scope 字段 + 自动创建 platform shared KB。

scope: 'project' (默认 - 已有 KB 都是) | 'platform' (新加)
"""
from __future__ import annotations

from alembic import op

revision = "046_v6_kb_scope"
down_revision = "045_v6_capability_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS scope VARCHAR(16) NOT NULL DEFAULT 'project'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_kb_scope ON knowledge_bases(scope)")
    # 旧 KB 全部按 project；platform KB 由 init_db 启动 seed 一条（依赖 admin user 存在，故不在此 migration 直 INSERT）


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kb_scope")
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS scope")
