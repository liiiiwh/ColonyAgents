"""agents.render_hint + agents.render_config — Agent 层声明输出渲染契约

把"渲染该 Agent 的输出用哪个 renderer + 哪些标签 / 顺序 / 阈值"从 ProjectNode 层
搬到 Agent 层。同一层与 `agents.produces_deliverable`（已存在）：

- `produces_deliverable`：Agent 输出**怎么落库**（artifact + S3 vs node.state）
- `render_hint` / `render_config`：Agent 输出**怎么渲染** UI

ProjectNode.node_config 仍保留作为"项目层 override"通道（rare use），但默认值由 Agent
给出，admin 在 `/admin/agents/<id>` 配置即可，节点表只读展示。

Revision ID: 017_agent_render_config
Revises: 016_materials
Create Date: 2026-05-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "017_agent_render_config"
down_revision: str | None = "016_materials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns("agents")}
    if "render_hint" not in existing:
        op.add_column(
            "agents",
            sa.Column("render_hint", sa.String(length=64), nullable=True),
        )
    if "render_config" not in existing:
        # JSONB 在 Postgres / fallback 到 SQLite JSON
        if bind.dialect.name == "postgresql":
            jcol = postgresql.JSONB(astext_type=sa.Text())
        else:
            jcol = sa.JSON()
        op.add_column(
            "agents",
            sa.Column("render_config", jcol, nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns("agents")}
    if "render_config" in existing:
        op.drop_column("agents", "render_config")
    if "render_hint" in existing:
        op.drop_column("agents", "render_hint")
