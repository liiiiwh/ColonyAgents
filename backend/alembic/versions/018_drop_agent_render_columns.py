"""drop agents.render_hint + agents.render_config

v0.4.18 起渲染契约改为前端 autoDetect（按数据形状自动选 renderer），
admin UI 不需要管理这些信息。Agent 想要中文标签等元信息可在输出 JSON 里塞 `_meta`。
v0.4.17 (017) 加的两列从此不用，drop 掉避免 schema 噪音。

Revision ID: 018_drop_agent_render_columns
Revises: 017_agent_render_config
Create Date: 2026-05-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "018_drop_agent_render_columns"
down_revision: str | None = "017_agent_render_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns("agents")}
    if "render_config" in existing:
        op.drop_column("agents", "render_config")
    if "render_hint" in existing:
        op.drop_column("agents", "render_hint")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns("agents")}
    if "render_hint" not in existing:
        op.add_column(
            "agents",
            sa.Column("render_hint", sa.String(length=64), nullable=True),
        )
    if "render_config" not in existing:
        if bind.dialect.name == "postgresql":
            jcol = postgresql.JSONB(astext_type=sa.Text())
        else:
            jcol = sa.JSON()
        op.add_column(
            "agents",
            sa.Column("render_config", jcol, nullable=False, server_default="{}"),
        )
