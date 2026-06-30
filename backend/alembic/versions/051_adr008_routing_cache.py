"""ADR-008 P4 · wechat_clawbot_accounts.routing_cache（WeChat Router 粘性路由缓存）。

{wechat_user_id: 上次路由到的 super target id}，连续自由消息粘同一 session。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "051_adr008_routing_cache"
down_revision = "050_v7_drop_agent_activities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wechat_clawbot_accounts",
        sa.Column(
            "routing_cache",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("wechat_clawbot_accounts", "routing_cache")
