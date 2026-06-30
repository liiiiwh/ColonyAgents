"""ADR-023 S6 · 删物料库 materials 表（与知识库职能重叠 + 协议零驱动 + 零使用）。

Revision ID: 074_drop_materials
Revises: 073_project_to_mission_rename
"""
from __future__ import annotations

from alembic import op

revision: str = "074_drop_materials"
down_revision: str | None = "073_project_to_mission_rename"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS materials")


def downgrade() -> None:
    # 绿地删除，不重建（如需恢复见 016_materials.py）
    pass
