"""v6.B · 扩展 agent_activities.kind CHECK 允许 redirect / thinking / memory_op / knowledge_op。

044 原 CHECK 只接 8 个 kind；v6.J + v6.B 加新 kind 后要扩。
"""
from __future__ import annotations

from alembic import op

revision = "047_v6_activity_kinds_expand"
down_revision = "046_v6_kb_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_activities DROP CONSTRAINT IF EXISTS ck_aa_kind")
    op.execute("""
        ALTER TABLE agent_activities ADD CONSTRAINT ck_aa_kind CHECK (
            kind IN ('tick','invoke_worker','llm_call','thinking','approval',
                     'clarification','user_chat','artifact_emit','escalation',
                     'redirect','memory_op','knowledge_op')
        )
    """)
    # status 也补 waiting_worker
    op.execute("ALTER TABLE agent_activities DROP CONSTRAINT IF EXISTS ck_aa_status")
    op.execute("""
        ALTER TABLE agent_activities ADD CONSTRAINT ck_aa_status CHECK (
            status IN ('pending','running','completed','failed','cancelled',
                       'waiting_user','waiting_worker')
        )
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE agent_activities DROP CONSTRAINT IF EXISTS ck_aa_kind")
    op.execute("""
        ALTER TABLE agent_activities ADD CONSTRAINT ck_aa_kind CHECK (
            kind IN ('tick','invoke_worker','llm_call','approval',
                     'clarification','user_chat','artifact_emit','escalation')
        )
    """)
