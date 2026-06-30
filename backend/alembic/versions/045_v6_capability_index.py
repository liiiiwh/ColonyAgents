"""v6 · worker_capability_actions 关系索引。

把 capability_contract.advertises[*] 拆成关系型表，让 Builder 能按
(action, side_effects, requires_approval, parallel_safe) 复合查询 worker。

写入路径：apply_worker_spec / agent_service.update_agent 完成后同步刷新；
读取路径：CapabilityIndex.find_workers(action=..., exclude_side_effects=...)。
"""
from __future__ import annotations

from alembic import op

revision = "045_v6_capability_index"
down_revision = "044_v6_activities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS worker_capability_actions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            worker_agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            capability VARCHAR(64) NOT NULL,
            action VARCHAR(128) NOT NULL,
            requires_approval BOOLEAN NOT NULL DEFAULT false,
            parallel_safe BOOLEAN NOT NULL DEFAULT true,
            idempotent BOOLEAN NOT NULL DEFAULT true,
            side_effects JSONB NULL,
            concurrency_hint TEXT NULL,
            rate_limit TEXT NULL,
            input_schema JSONB NULL,
            output_schema JSONB NULL,
            since VARCHAR(32) NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_wca_worker_action UNIQUE (worker_agent_id, action)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_wca_action ON worker_capability_actions(action)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wca_capability ON worker_capability_actions(capability)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wca_requires_approval ON worker_capability_actions(requires_approval)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS worker_capability_actions")
