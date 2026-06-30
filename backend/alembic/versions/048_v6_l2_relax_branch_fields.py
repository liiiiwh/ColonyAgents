"""ADR-006 Phase L.2 · session_branches deprecated 字段 relax (不 drop)。

ADR-006 决议 1 session = 1 active thread。session_branches 表保留向后兼容，
但 v6 起 is_current / branch_number / parent_branch_id 字段 deprecated：
- 不再由代码主动维护
- 把 NOT NULL / UNIQUE 约束 relax 成 nullable，避免新插入逻辑被旧约束卡

不 drop 字段（外部脚本可能仍在读，更激进的 drop 走 048b 二阶段）；
也允许在迁移完成前继续兼容老查询。

补加新增 lifecycle_transition 到 agent_activities.kind CHECK 列表（047 的延伸；
LifecycleService 现在写这个 kind 留证）。
"""
from __future__ import annotations

from alembic import op


revision = "048_v6_l2_relax_branch_fields"
down_revision = "047_v6_activity_kinds_expand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # session_branches deprecated 字段 relax 成 nullable + drop is_current 唯一性
    op.execute("ALTER TABLE session_branches ALTER COLUMN branch_number DROP NOT NULL")
    op.execute("ALTER TABLE session_branches ALTER COLUMN is_current DROP NOT NULL")
    # 若历史上加了 unique 约束 (session_id, is_current=true)，drop 掉
    op.execute("DROP INDEX IF EXISTS ix_session_branches_session_current")

    # 扩 agent_activities.kind 接受 lifecycle_transition
    op.execute("ALTER TABLE agent_activities DROP CONSTRAINT IF EXISTS ck_aa_kind")
    op.execute("""
        ALTER TABLE agent_activities ADD CONSTRAINT ck_aa_kind CHECK (
            kind IN ('tick','invoke_worker','llm_call','thinking','approval',
                     'clarification','user_chat','artifact_emit','escalation',
                     'redirect','memory_op','knowledge_op',
                     'lifecycle_transition')
        )
    """)


def downgrade() -> None:
    # 把字段恢复 NOT NULL — 但只有当数据没 NULL 时才能跑；下行不保证可执行
    op.execute(
        "UPDATE session_branches SET branch_number = COALESCE(branch_number, 1) WHERE branch_number IS NULL"
    )
    op.execute(
        "UPDATE session_branches SET is_current = COALESCE(is_current, false) WHERE is_current IS NULL"
    )
    op.execute("ALTER TABLE session_branches ALTER COLUMN branch_number SET NOT NULL")
    op.execute("ALTER TABLE session_branches ALTER COLUMN is_current SET NOT NULL")

    # 收缩回 047 的 CHECK
    op.execute("ALTER TABLE agent_activities DROP CONSTRAINT IF EXISTS ck_aa_kind")
    op.execute("""
        ALTER TABLE agent_activities ADD CONSTRAINT ck_aa_kind CHECK (
            kind IN ('tick','invoke_worker','llm_call','thinking','approval',
                     'clarification','user_chat','artifact_emit','escalation',
                     'redirect','memory_op','knowledge_op')
        )
    """)
