"""v3 hardening · V16/V22/V37/V38/V42/V45/V55 + 全局 system_settings 扩展。

幂等：所有 DDL/INSERT 都用 IF NOT EXISTS / ON CONFLICT。

- V22 项目内同时只允许 1 个 pending capability_missing escalation (DB 约束)
- 扩展 system_settings 配置项（compression / escalation quota / hardening 等全部入后台可调）
"""
from __future__ import annotations

from alembic import op

revision = "041_v3_hardening_v22_v55"
down_revision = "039_projects_compression_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── V22 · 同 super 不允许 ≥2 个 pending capability_missing（category='structural'）escalation ──
    # 用 PARTIAL UNIQUE INDEX；与现有 ix_pe_uniq_per_day（fingerprint dedup）正交
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_pe_uniq_pending_structural
        ON project_escalations(project_id)
        WHERE status IN ('pending', 'delivered') AND category = 'structural'
    """)

    # ── 新增 system_settings 行（admin 可调全局配置）──
    # 已存在则不覆盖（ON CONFLICT DO NOTHING）
    op.execute("""
        INSERT INTO system_settings (key, value, description) VALUES
        -- V16 capability 申请配额 + 自动 dismiss
        ('escalation.capability_quota_per_super', '3'::jsonb,
         'V16 同 super 最多并发 N 个 pending capability 请求；超出 reject'),
        ('escalation.auto_dismiss_days', '7'::jsonb,
         'V16/V21 pending escalation 超 N 天自动 dismiss + 推 wechat 提醒'),
        -- V37 worker 反问循环上限
        ('worker.max_clarification_rounds', '3'::jsonb,
         'V37 同一 invoke_worker call 内允许 worker 反问的最大轮数；超出强制 request_approval'),
        -- V38 ToolMessage 大小上限
        ('worker.tool_message_max_kb', '50'::jsonb,
         'V38 super-worker thread 单条消息内容上限（KB）；超过自动转 S3 + 替换为 URL'),
        -- V42 worker.protocol_md 禁词
        ('factory.worker_protocol_forbidden_words', '["request_approval","project_escalate","agent_protocol_propose","agent_protocol_apply","invoke_workers_parallel","request_new_capability"]'::jsonb,
         'V42 Factory Postflight 校验 worker.protocol_md 不可含的 super-only 词；命中即 fail'),
        -- 既有项（兼容旧 plan 文档；如已存在沿用）
        ('compression.cache_ttl_seconds', '60'::jsonb,
         'session_service 进程内压缩配置缓存 TTL；admin PATCH 后会立即 invalidate'),
        ('daemon.heartbeat_interval_seconds', '30'::jsonb,
         'super daemon 心跳频率；scheduler 据此判活 / 标 stale'),
        ('invoke_worker.timeout_seconds', '600'::jsonb,
         'invoke_worker 单次 worker 运行超时；超时记 status=timeout'),
        ('invoke_worker.max_nesting_depth', '2'::jsonb,
         'V17 super 调 worker 调 worker 的栈深上限；超出抛错（默认禁止 worker 调 invoke_worker）'),
        ('return_result.artifact_bytes_max_mb', '100'::jsonb,
         'V18 return_result 单次 artifact_bytes_b64 大小上限（MB）；超过强制改走 s3_upload + artifact_url'),
        ('worker_invocation_log.archive_summary_enabled', 'false'::jsonb,
         'V55 是否在 TTL 删除前先归档周聚合到 worker_invocation_archive 表（未来扩展）')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pe_uniq_pending_structural")
    op.execute("""
        DELETE FROM system_settings WHERE key IN (
            'escalation.capability_quota_per_super',
            'escalation.auto_dismiss_days',
            'worker.max_clarification_rounds',
            'worker.tool_message_max_kb',
            'factory.worker_protocol_forbidden_words',
            'compression.cache_ttl_seconds',
            'daemon.heartbeat_interval_seconds',
            'invoke_worker.timeout_seconds',
            'invoke_worker.max_nesting_depth',
            'return_result.artifact_bytes_max_mb',
            'worker_invocation_log.archive_summary_enabled'
        )
    """)
