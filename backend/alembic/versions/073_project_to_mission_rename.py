"""ADR-022 · Project→Mission 全量改名：表 + 列重命名（零数据变更）。

运行时/域语言早已是 Mission（ADR-018 mission-only）；本迁移把仍叫 project* 的
持久层对象统一改名到 mission*，与 ORM 模型（models/mission.py）对齐。

纯重命名，不动数据/不增删列。Postgres `ALTER TABLE IF EXISTS ... RENAME` 幂等友好。

Revision ID: 073_project_to_mission_rename
Revises: 072_fix_thread_memory_id_type
"""
from __future__ import annotations

from alembic import op

revision: str = "073_project_to_mission_rename"
down_revision: str | None = "072_fix_thread_memory_id_type"
branch_labels = None
depends_on = None


# (old_table, new_table)
_TABLES = [
    ("projects", "missions"),
    ("project_run_state", "mission_run_state"),
    ("project_schedule", "mission_schedule"),
    ("project_agent_memory", "mission_agent_memory"),
    ("project_nodes", "mission_nodes"),
    ("project_escalations", "mission_escalations"),
    ("project_agent_memory_revisions", "mission_agent_memory_revisions"),
    ("project_approval_channels", "mission_approval_channels"),
]

# 所有带 project_id 列的表 → mission_id（含 5 张已改名的 mission 子表 + 7 张仅持 FK 列的表）
_PROJECT_ID_TABLES = [
    "mission_run_state",
    "mission_schedule",
    "mission_agent_memory",
    "mission_nodes",
    "mission_escalations",
    "mission_approval_channels",
    "pending_approvals",
    "builder_work_claims",
    "builder_work_logs",
    "knowledge_bases",
    "remote_skill_install",
    "wechat_outbox",
]

# super_project_id → super_mission_id
_SUPER_PROJECT_ID_TABLES = [
    "worker_invocation_log",
    "super_pending_messages",
]


def upgrade() -> None:
    for old, new in _TABLES:
        op.execute(f"ALTER TABLE IF EXISTS {old} RENAME TO {new}")
    for tbl in _PROJECT_ID_TABLES:
        op.execute(f"ALTER TABLE IF EXISTS {tbl} RENAME COLUMN project_id TO mission_id")
    for tbl in _SUPER_PROJECT_ID_TABLES:
        op.execute(f"ALTER TABLE IF EXISTS {tbl} RENAME COLUMN super_project_id TO super_mission_id")


def downgrade() -> None:
    for tbl in _SUPER_PROJECT_ID_TABLES:
        op.execute(f"ALTER TABLE IF EXISTS {tbl} RENAME COLUMN super_mission_id TO super_project_id")
    for tbl in _PROJECT_ID_TABLES:
        op.execute(f"ALTER TABLE IF EXISTS {tbl} RENAME COLUMN mission_id TO project_id")
    for old, new in _TABLES:
        op.execute(f"ALTER TABLE IF EXISTS {new} RENAME TO {old}")
