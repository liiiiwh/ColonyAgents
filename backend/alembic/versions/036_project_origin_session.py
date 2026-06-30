"""L3：origin_session_id + escalation_quota_remaining 落到 projects.workflow_config JSONB

Revision ID: 036_project_origin_session
Revises: 035_agent_protocol_history
Create Date: 2026-05-23

设计变更（vs 计划）：原本想给 projects 加 2 列，但 ALTER TABLE projects 在生产
（活跃 daemon 长 SELECT）锁竞争太严重——`agents` 与 `projects` 都受影响。

折中：直接复用现有 `projects.workflow_config: JSONB` 存：
- `workflow_config.origin_session_id` (str UUID)
- `workflow_config.escalation_quota_remaining` (int, default 3)

读取从 ORM 透明（workflow_config 是 JSONB / dict）；nightly quota 重置 job 改 dict 即可。
fingerprint 唯一索引由 037 那张 project_escalations 表本身的 unique 实现。

这个 migration 实际是 no-op（只占 alembic 序号）。
"""

from __future__ import annotations

revision: str = "036_project_origin_session"
down_revision: str | None = "035_agent_protocol_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # no-op：origin_session_id / escalation_quota_remaining 走 workflow_config JSONB
    pass


def downgrade() -> None:
    pass
