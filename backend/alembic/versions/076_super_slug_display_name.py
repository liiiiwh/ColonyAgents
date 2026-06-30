"""Super 身份字段：agents.slug + display_name（URL 路由 + 标题用，不再借 agent.name）。

/mission/<super_slug>/<mission> 与「Super · <display_name>」需要 super 有干净 slug/显示名。
回填：Builder Supervisor → slug='builder' / display='Colony Builder'；其它 super → sluggify(name)/name。

Revision ID: 076_super_slug_display_name
Revises: 075_kb_per_super
"""
from __future__ import annotations

from alembic import op

revision: str = "076_super_slug_display_name"
down_revision: str | None = "075_kb_per_super"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS slug VARCHAR(128)")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS display_name VARCHAR(128)")
    # Builder Supervisor（监管 slug='builder' 的系统 mission）→ well-known 'builder' / 'Colony Builder'
    op.execute(
        "UPDATE agents SET slug='builder', display_name='Colony Builder' "
        "WHERE id = (SELECT supervisor_agent_id FROM missions WHERE slug='builder' LIMIT 1)"
    )
    # 其它 super：sluggify(name) + display=name（仅当还没 slug）
    op.execute(
        "UPDATE agents SET "
        "slug = trim(both '-' from lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g'))), "
        "display_name = name "
        "WHERE kind='super' AND slug IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_agents_slug ON agents(slug) WHERE slug IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agents_slug")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS display_name")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS slug")
