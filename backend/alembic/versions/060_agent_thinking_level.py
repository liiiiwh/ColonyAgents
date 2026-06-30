"""agents.thinking_level —— 按 Agent 控制模型内置思考档位

新增 agents.thinking_level（off/low/medium/high，默认 off）。_build_llm 按当前模型家族
把档位映射成各家具体参数（gemini thinkingBudget / claude budget_tokens / 其它 reasoning_effort）。
回填：旧 enable_thinking=True 的 Agent → "medium"（claude budget_tokens=8000，与旧默认强度一致），否则 "off"。
enable_thinking 列保留作回退兼容（旧客户端/数据）。

Revision ID: 060_agent_thinking_level
Revises: 059_drop_meshy_skills
Create Date: 2026-06-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "060_agent_thinking_level"
down_revision: str | None = "059_drop_meshy_skills"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "thinking_level",
            sa.String(length=8),
            nullable=False,
            server_default="off",
        ),
    )
    # 回填：原 enable_thinking=True → medium（保留"开思考"语义，claude=8000 与旧默认强度一致），其余 off
    op.execute("UPDATE agents SET thinking_level = 'medium' WHERE enable_thinking IS true")
    # 去掉 server_default，交由应用层 default 控制（与其它列风格一致）
    op.alter_column("agents", "thinking_level", server_default=None)


def downgrade() -> None:
    op.drop_column("agents", "thinking_level")
