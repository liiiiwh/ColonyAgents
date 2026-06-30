"""v5 · memory revisions table + v5 system_settings keys (live events / approval / memory edit)。

幂等：CREATE IF NOT EXISTS + ON CONFLICT DO NOTHING。
"""
from __future__ import annotations

from alembic import op

revision = "043_v5_memory_revs_and_settings"
down_revision = "042_super_pending_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) memory revisions 表（v5 部分 D · 安全 editor 用）
    op.execute("""
        CREATE TABLE IF NOT EXISTS project_agent_memory_revisions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            memory_id UUID NOT NULL REFERENCES project_agent_memory(id) ON DELETE CASCADE,
            memory_md TEXT NOT NULL,
            edited_by VARCHAR(64),
            edited_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            reason TEXT,
            is_clear_op BOOLEAN NOT NULL DEFAULT false
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pamr_memory_time "
        "ON project_agent_memory_revisions(memory_id, edited_at DESC)"
    )

    # 2) v5 system_settings 4 个新行
    op.execute("""
        INSERT INTO system_settings (key, value, description) VALUES
        ('live_events_enabled', 'true'::jsonb,
         'v5 · super SSE 是否走实时 event_bus；false 退化到老 2s poll'),
        ('inline_approval_enabled', 'true'::jsonb,
         'v5 · request_approval 是否在 chat 流推 inline card；false 仅微信'),
        ('memory_edit_enabled', 'false'::jsonb,
         'v5 · 是否允许 admin 编辑 super 长期记忆（默认关；仅 viewer + clear 可用）'),
        ('event_bus.backend', '"inprocess"'::jsonb,
         'v5 · event_bus 后端实现；当前仅 inprocess；v5.1 加 pg_notify')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_agent_memory_revisions")
    op.execute("""
        DELETE FROM system_settings WHERE key IN (
            'live_events_enabled',
            'inline_approval_enabled',
            'memory_edit_enabled',
            'event_bus.backend'
        )
    """)
