"""agents.kind 非空保障：禁止 kind=NULL（会让 agent 在 Agents 页两个 tab 都不可见）。

回填残留 NULL/'' → 'worker'，列改 NOT NULL + server_default 'worker'，从结构上保证每个 agent
都有 kind、都在「Agents」页可见。038 当初加列时允许 NULL 以兼容老数据，至此收口。

Revision ID: 077_agent_kind_not_null
Revises: 076_super_slug_display_name
"""
from __future__ import annotations

from alembic import op

revision: str = "077_agent_kind_not_null"
down_revision: str | None = "076_super_slug_display_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE agents SET kind='worker' WHERE kind IS NULL OR trim(kind) = ''")
    op.execute("ALTER TABLE agents ALTER COLUMN kind SET DEFAULT 'worker'")
    op.execute("ALTER TABLE agents ALTER COLUMN kind SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE agents ALTER COLUMN kind DROP NOT NULL")
    op.execute("ALTER TABLE agents ALTER COLUMN kind DROP DEFAULT")
