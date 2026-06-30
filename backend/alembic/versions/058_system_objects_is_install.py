"""ADR-015 · 平台系统对象 is_system + 安装标记 is_install

- agents.is_system / projects.is_system（默认 False）
- 回填：slug='builder' 的 Project + 其 supervisor + 其全部 project_nodes 上的 agent → is_system=True
- system_settings['is_install']：已存在 Builder Project → '1'（存量部署不被当成未安装），否则 '0'

Revision ID: 058_system_objects_is_install
Revises: 057_session_relay
"""
from alembic import op

revision = "058_system_objects_is_install"
down_revision = "057_session_relay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS is_system BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_system BOOLEAN NOT NULL DEFAULT false")

    # 回填 Builder 自举集
    op.execute("UPDATE projects SET is_system = true WHERE slug = 'builder'")
    op.execute("""
        UPDATE agents SET is_system = true
         WHERE id IN (SELECT supervisor_agent_id FROM projects WHERE slug = 'builder')
    """)
    op.execute("""
        UPDATE agents SET is_system = true
         WHERE id IN (
            SELECT pn.agent_id FROM project_nodes pn
              JOIN projects p ON p.id = pn.project_id
             WHERE p.slug = 'builder'
         )
    """)

    # is_install：已有 Builder Project → 视为已安装（不弹初始化向导）。value 为 JSONB。
    op.execute("""
        INSERT INTO system_settings (key, value, description)
        SELECT 'is_install',
               (CASE WHEN EXISTS (SELECT 1 FROM projects WHERE slug = 'builder')
                     THEN '1' ELSE '0' END)::jsonb,
               'ADR-015 平台安装标记：0=未安装(弹初始化向导) 1=已安装'
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM system_settings WHERE key = 'is_install'")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS is_system")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS is_system")
