"""agents.enable_thinking: 每个 Agent 独立控制模型思考开关（默认关闭）

默认 False 的语义：
- 跨 provider 都会尽量关闭模型内置 thinking / reasoning：
  * anthropic（Claude 4.x 直连）：`thinking={"type":"disabled"}`
  * gemini：`extra_body.generationConfig.thinkingConfig.thinkingLevel="off"`
  * 其它（含 openai / deepseek / custom / nebula-openai-compat）：`reasoning_effort="minimal"`
- True 时不再注入任何思考控制参数，让 provider 走默认预算；Agent.extra_config
  仍可继续手动覆盖（如 thinking={type,budget_tokens} / reasoning_effort="high"）。

Revision ID: 014_agent_enable_thinking
Revises: 013_project_access_control
Create Date: 2026-04-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014_agent_enable_thinking"
down_revision: str | None = "013_project_access_control"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns("agents")}
    if "enable_thinking" in existing:
        return
    op.add_column(
        "agents",
        sa.Column(
            "enable_thinking",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns("agents")}
    if "enable_thinking" in existing:
        op.drop_column("agents", "enable_thinking")
