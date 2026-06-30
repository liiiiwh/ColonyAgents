"""v6 · agent_activities first-class Activity 表（树形）。

替代当前散在 worker_invocation_log / messages / pending_approvals 的
"super 正在干啥" 真相 — 一处写入，一处查询，一处订阅。
"""
from __future__ import annotations

from alembic import op

revision = "044_v6_activities"
down_revision = "043_v5_memory_revs_and_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_activities (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            parent_id UUID NULL REFERENCES agent_activities(id) ON DELETE CASCADE,
            super_id UUID NOT NULL,
            project_id UUID NULL,
            kind VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'running',
            started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            finished_at TIMESTAMP WITH TIME ZONE NULL,
            duration_ms INTEGER NULL,
            payload JSONB NULL,
            result JSONB NULL,
            error_msg TEXT NULL,
            cost_tokens INTEGER NULL,
            cost_cents INTEGER NULL,
            channel UUID NULL,
            CONSTRAINT ck_aa_kind CHECK (
                kind IN ('tick','invoke_worker','llm_call','approval',
                         'clarification','user_chat','artifact_emit','escalation')
            ),
            CONSTRAINT ck_aa_status CHECK (
                status IN ('pending','running','completed','failed',
                           'cancelled','waiting_user')
            )
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_aa_super_started ON agent_activities(super_id, started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_aa_parent ON agent_activities(parent_id) WHERE parent_id IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_aa_status_open ON agent_activities(super_id, status) WHERE status IN ('running','waiting_user','pending')")
    op.execute("CREATE INDEX IF NOT EXISTS ix_aa_kind ON agent_activities(kind)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_activities")
