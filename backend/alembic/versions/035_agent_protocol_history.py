"""L2 自调优：agent_protocol_history + agent_protocol_proposals + agents.protocol_version

Revision ID: 035_agent_protocol_history
Revises: 034_wechat_outbox_sent_at_tz
Create Date: 2026-05-23

设计动机：
- supervisor 自动调优 worker 的 protocol_md 必须有审计 / 撤销链路，不能直接 `agent_update`
- propose → request_approval → apply → evaluate → 自动 revert 全闭环
- H4 expiry：proposals 24h 过期；H5 history 永不删 factory_initial / human_admin；
  H15 supervisor 自己不能 propose 自己（业务层校验）

H12 幂等：所有 DDL 走 `IF NOT EXISTS`（PG）或 try/except，重跑安全
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "035_agent_protocol_history"
down_revision: str | None = "034_wechat_outbox_sent_at_tz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 注：不在 agents 表加 protocol_version 列（避免对热表做 DDL 引起锁竞争）。
    # version 完全派生于 agent_protocol_history（每个 agent 用 MAX(version) 求当前版本）。

    # 1) agent_protocol_history
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_protocol_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            soul_md TEXT NULL,
            protocol_md TEXT NULL,
            applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            applied_by_kind VARCHAR(32) NOT NULL,
            applied_by_ref VARCHAR(256) NULL,
            trigger_summary VARCHAR(512) NULL,
            rollback_of_version INTEGER NULL,
            metrics_baseline JSONB NULL,
            CONSTRAINT uq_agent_protocol_history_agent_version UNIQUE (agent_id, version),
            CONSTRAINT ck_aph_by_kind CHECK (applied_by_kind IN
                ('factory_initial','supervisor_self_tune','builder_session','human_admin'))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_aph_agent_applied_at "
        "ON agent_protocol_history(agent_id, applied_at DESC)"
    )

    # 3) agent_protocol_proposals
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_protocol_proposals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            proposer_session_id UUID NULL REFERENCES sessions(id) ON DELETE SET NULL,
            proposer_agent_node_name VARCHAR(128) NULL,
            proposed_soul_md TEXT NULL,
            proposed_protocol_md TEXT NULL,
            diff_summary VARCHAR(2000) NOT NULL DEFAULT '',
            trigger_summary VARCHAR(512) NOT NULL DEFAULT '',
            expected_improvement VARCHAR(1000) NOT NULL DEFAULT '',
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            applied_at TIMESTAMP WITH TIME ZONE NULL,
            applied_history_version INTEGER NULL,
            CONSTRAINT ck_app_status CHECK (status IN
                ('pending','applied','rejected','expired','superseded_by_existing'))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_app_agent_status "
        "ON agent_protocol_proposals(agent_id, status)"
    )
    # H4 并发锁：同 agent 同时最多 1 条 pending（partial unique index）
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_app_one_pending_per_agent "
        "ON agent_protocol_proposals(agent_id) WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_app_one_pending_per_agent")
    op.execute("DROP INDEX IF EXISTS ix_app_agent_status")
    op.execute("DROP TABLE IF EXISTS agent_protocol_proposals")
    op.execute("DROP INDEX IF EXISTS ix_aph_agent_applied_at")
    op.execute("DROP TABLE IF EXISTS agent_protocol_history")
