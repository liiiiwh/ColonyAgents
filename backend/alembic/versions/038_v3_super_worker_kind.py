"""v3 · Super/Worker first-class + 持久 thread + 三级压缩 + worker invocation log

Revision ID: 038_v3_super_worker_kind
Revises: 037_project_escalations
Create Date: 2026-05-24

集中加列：
- agents.kind / capability                         (B1/B2 super/worker 区分 + 平台 worker catalog)
- projects.lifecycle_status / paused_reason        (B5 super 暂停 / 恢复状态机)
- sessions.opened_by                               (R25 Builder 双客户模式路由)
- session_branches.thread_kind / compression_config (R16 super-worker thread + R21 thread 级压缩配置)

新表：
- worker_invocation_log                           (R26 worker 观察页大盘查询性能)
- system_settings                                 (R19/R20 平台级压缩配置 admin 可调)

所有 DDL 用 IF NOT EXISTS / DO 块包裹，幂等可重跑。
ALTER agents 用 NULL 列避免对热表加 ACCESS EXCLUSIVE 锁阻塞 daemon。
"""

from __future__ import annotations

from alembic import op

revision: str = "038_v3_super_worker_kind"
down_revision: str | None = "037_project_escalations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── agents：kind / capability ──
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NULL")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS capability VARCHAR(64) NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agents_kind ON agents(kind) WHERE kind IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agents_capability ON agents(capability) WHERE capability IS NOT NULL")
    # backfill kind from existing category for known agents
    op.execute("""
        UPDATE agents SET kind='super'
        WHERE kind IS NULL
          AND id IN (SELECT supervisor_agent_id FROM projects WHERE supervisor_agent_id IS NOT NULL)
    """)
    op.execute("UPDATE agents SET kind='builder' WHERE kind IS NULL AND category='builder'")
    op.execute("UPDATE agents SET kind='installer' WHERE kind IS NULL AND category='installer'")
    op.execute("UPDATE agents SET kind='tester' WHERE kind IS NULL AND category='tester'")
    op.execute("UPDATE agents SET kind='worker' WHERE kind IS NULL")
    # 注意：未设 NOT NULL 约束（生产 backfill 安全 + 留 NULL 给未来类型）

    # ── projects：lifecycle_status / paused_reason ──
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'stopped'")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS paused_reason TEXT NULL")
    # R21 super 级压缩配置 override（NULL = 用平台默认）
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS compression_config JSONB NULL")
    # backfill from runtime_status
    op.execute("UPDATE projects SET lifecycle_status='running' WHERE runtime_status='running' AND lifecycle_status='stopped'")
    op.execute("UPDATE projects SET lifecycle_status='error' WHERE runtime_status='error' AND lifecycle_status='stopped'")

    # ── sessions：opened_by ──
    op.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS opened_by VARCHAR(64) NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_opened_by ON sessions(opened_by) WHERE opened_by IS NOT NULL")
    # 老 session 默认 'user'（user-initiated chat）；daemon scope 改 'system'
    op.execute("UPDATE sessions SET opened_by='user' WHERE opened_by IS NULL AND scope='orchestrator'")
    op.execute("UPDATE sessions SET opened_by='system' WHERE opened_by IS NULL AND scope='daemon'")

    # ── session_branches：thread_kind / compression_config ──
    op.execute("ALTER TABLE session_branches ADD COLUMN IF NOT EXISTS thread_kind VARCHAR(32) NULL")
    op.execute("ALTER TABLE session_branches ADD COLUMN IF NOT EXISTS compression_config JSONB NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sb_thread_kind ON session_branches(thread_kind) WHERE thread_kind IS NOT NULL")
    # 不 backfill thread_kind；老 branch 保持 NULL（legacy 路径）

    # ── worker_invocation_log（R26 性能表，反正规化）──
    op.execute("""
        CREATE TABLE IF NOT EXISTS worker_invocation_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            worker_agent_id UUID NOT NULL,
            super_agent_id UUID NOT NULL,
            super_project_id UUID NULL,
            thread_branch_id UUID NULL,
            action VARCHAR(128) NOT NULL,
            started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            finished_at TIMESTAMP WITH TIME ZONE NULL,
            duration_ms INTEGER NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'started',
            error_msg TEXT NULL,
            tokens_in INTEGER NULL,
            tokens_out INTEGER NULL,
            artifact_count INTEGER NOT NULL DEFAULT 0,
            artifact_total_bytes BIGINT NOT NULL DEFAULT 0,
            needs_clarification_round INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT ck_wil_status CHECK (status IN ('started','completed','failed','needs_clarification','timeout'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_wil_worker_time ON worker_invocation_log(worker_agent_id, started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wil_super_time ON worker_invocation_log(super_agent_id, started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wil_status ON worker_invocation_log(status)")

    # ── system_settings（admin 可调平台配置）──
    op.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key VARCHAR(128) PRIMARY KEY,
            value JSONB NOT NULL,
            description VARCHAR(512) NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_by VARCHAR(128) NULL
        )
    """)
    # seed 行业标准默认压缩配置（如已有则不覆盖）
    op.execute("""
        INSERT INTO system_settings (key, value, description) VALUES
        ('compression.threshold_tokens', '30000'::jsonb, 'L1 platform default: trigger compression when accumulated tokens >= this'),
        ('compression.keep_recent_messages', '20'::jsonb, 'L1 platform default: keep N most recent messages uncompressed'),
        ('compression.target_ratio', '0.3'::jsonb, 'L1 platform default: compress old messages to ~30% of original size'),
        ('worker_invocation_log.ttl_days', '90'::jsonb, 'V55 retention; older rows archived to summary + deleted'),
        ('escalation.daily_quota_per_project', '3'::jsonb, 'L3 quota; reset nightly'),
        ('dev.max_daemon_ticks', '0'::jsonb, 'V56 token guard; 0=unlimited (prod); set >0 in dev to auto-stop')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS system_settings")
    op.execute("DROP INDEX IF EXISTS ix_wil_status")
    op.execute("DROP INDEX IF EXISTS ix_wil_super_time")
    op.execute("DROP INDEX IF EXISTS ix_wil_worker_time")
    op.execute("DROP TABLE IF EXISTS worker_invocation_log")
    op.execute("DROP INDEX IF EXISTS ix_sb_thread_kind")
    op.execute("ALTER TABLE session_branches DROP COLUMN IF EXISTS compression_config")
    op.execute("ALTER TABLE session_branches DROP COLUMN IF EXISTS thread_kind")
    op.execute("DROP INDEX IF EXISTS ix_sessions_opened_by")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS opened_by")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS paused_reason")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS lifecycle_status")
    op.execute("DROP INDEX IF EXISTS ix_agents_capability")
    op.execute("DROP INDEX IF EXISTS ix_agents_kind")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS capability")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS kind")
