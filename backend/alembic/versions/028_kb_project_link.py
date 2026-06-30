"""KB ↔ Project 1:1 + KB tags / purpose

Revision ID: 028_kb_project_link
Revises: 027_branch_workspace_version
Create Date: 2026-05-20

每个 Project 自动持有一条 KB。新增列：
- knowledge_bases.project_id  uuid NULL UNIQUE FK projects(id) ON DELETE CASCADE
- knowledge_bases.tags        json NOT NULL DEFAULT []
- knowledge_bases.purpose     varchar(256) NOT NULL DEFAULT ''

兼容已有数据：所有现有 KB 标 project_id=NULL（独立 KB，admin 手建）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "028_kb_project_link"
down_revision: str | None = "027_branch_workspace_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("project_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_bases_project",
        "knowledge_bases",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_knowledge_bases_project_id",
        "knowledge_bases",
        ["project_id"],
    )
    op.create_index(
        "ix_knowledge_bases_project_id",
        "knowledge_bases",
        ["project_id"],
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "tags",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "purpose",
            sa.String(length=256),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "purpose")
    op.drop_column("knowledge_bases", "tags")
    op.drop_index("ix_knowledge_bases_project_id", table_name="knowledge_bases")
    op.drop_constraint(
        "uq_knowledge_bases_project_id", "knowledge_bases", type_="unique"
    )
    op.drop_constraint(
        "fk_knowledge_bases_project", "knowledge_bases", type_="foreignkey"
    )
    op.drop_column("knowledge_bases", "project_id")
