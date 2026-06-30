"""drop meshy skills (meshy_image_to_3d_create / meshy_fetch_3d)

下线 Meshy image-to-3d 两个内置 skill：删 agent 绑定 + skills 行。幂等。

Revision ID: 059_drop_meshy_skills
Revises: 058_system_objects_is_install
"""

from alembic import op

revision = "059_drop_meshy_skills"
down_revision = "058_system_objects_is_install"
branch_labels = None
depends_on = None

_SLUGS = ("meshy_image_to_3d_create", "meshy_fetch_3d")


def upgrade() -> None:
    conn = op.get_bind()
    # 先删 agent_skills 绑定（避免 FK），再删 skills 行
    # slug 是固定常量，直接字面 IN（避免驱动对 list 参数的 paramstyle 差异）
    _in = "('meshy_image_to_3d_create', 'meshy_fetch_3d')"
    conn.exec_driver_sql(
        f"DELETE FROM agent_skills WHERE skill_id IN (SELECT id FROM skills WHERE slug IN {_in})"
    )
    conn.exec_driver_sql(f"DELETE FROM skills WHERE slug IN {_in}")


def downgrade() -> None:
    # 内置 skill 由 registry seed 重建，迁移不负责回填。
    pass
