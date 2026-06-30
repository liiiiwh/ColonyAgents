"""v4 · super_pending_messages 表 + 实时对话相关 system_settings。

支持「用户随时跟 super 对话（/btw 风格）」：
- 用户消息进 super_pending_messages 队列
- 立即 cancel 当前 tick + trigger 新 tick
- run_once 入口 pop 队列 + 合并到 prompt §3 段

幂等：IF NOT EXISTS / ON CONFLICT DO NOTHING。
"""
from __future__ import annotations

from alembic import op

revision = "042_super_pending_messages"
down_revision = "041_v3_hardening_v22_v55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── super_pending_messages 表（用户 /btw 消息队列）──
    op.execute("""
        CREATE TABLE IF NOT EXISTS super_pending_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            super_project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            super_agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            meta JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            consumed_at TIMESTAMP WITH TIME ZONE NULL,
            CONSTRAINT ck_spm_status CHECK (status IN ('pending','consumed','dropped'))
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_spm_super_pending
        ON super_pending_messages(super_project_id, created_at ASC)
        WHERE status = 'pending'
    """)

    # ── v4 新增 5 个 system_settings（admin 可调）──
    op.execute("""
        INSERT INTO system_settings (key, value, description) VALUES
        ('super.user_chat_cancel_timeout_seconds', '10'::jsonb,
         'V4 cancel 当前 tick 后等待 worker cooperative cancel 的最大秒数；超时强 cancel Task'),
        ('super.auto_trigger_on_user_msg', 'true'::jsonb,
         'V4 用户发消息后是否立即触发下一次 tick（false = 仅入队列等下次 schedule）'),
        ('super.max_pending_msgs_per_super', '20'::jsonb,
         'V4 super_pending_messages 单 super 上限；超出 reject 用户新消息（防 DoS）'),
        ('super.cancel_burst_window_seconds', '5'::jsonb,
         'V4/F2/R-F2 burst window 内 cancel 计数阈值；超过 3 次写 throttle log'),
        ('super.pending_msg_max_kb_per_msg', '50'::jsonb,
         'V4/F3/R-F3 单条 pending 消息体积上限（同 V38）；超出走 S3 offload')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_spm_super_pending")
    op.execute("DROP TABLE IF EXISTS super_pending_messages")
    op.execute("""
        DELETE FROM system_settings WHERE key IN (
            'super.user_chat_cancel_timeout_seconds',
            'super.auto_trigger_on_user_msg',
            'super.max_pending_msgs_per_super',
            'super.cancel_burst_window_seconds',
            'super.pending_msg_max_kb_per_msg'
        )
    """)
