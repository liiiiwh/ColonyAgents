"""agents.max_output_tokens: 单次 LLM 调用的最大输出 token 上限（默认 5000）

默认 5000 的理由：
- Nebula + Claude 实测 ~54 tok/s，5000 tok ≈ 93s，与 Worker 5 分钟预算匹配
- 之前未限制时，单次生成可达 14000 tok（bb9107e4 session 观察），耗时 4 分 20 秒，
  再叠加 TTFT 重试 + Supervisor 收尾调用，必然超出 300s Worker 预算 → Worker 被 cancel
- 命中 length 限制时由 ResilientChatLiteLLM 自动对**纯文本响应**续写；tool_call 参数
  被截会抛错，让 Agent 分块写（见 resilient_llm.py 的 continuation 逻辑）

Revision ID: 015_agent_max_output_tokens
Revises: 014_agent_enable_thinking
Create Date: 2026-04-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015_agent_max_output_tokens"
down_revision: str | None = "014_agent_enable_thinking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns("agents")}
    if "max_output_tokens" in existing:
        return
    op.add_column(
        "agents",
        sa.Column(
            "max_output_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30000"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns("agents")}
    if "max_output_tokens" in existing:
        op.drop_column("agents", "max_output_tokens")
