"""R21 · 补 projects.compression_config 列（038 在该字段加入 ORM 之前已 apply）。

幂等：IF NOT EXISTS。
"""
from __future__ import annotations

from alembic import op

revision = "039_projects_compression_config"
down_revision = "038_v3_super_worker_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS compression_config JSONB NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS compression_config")
