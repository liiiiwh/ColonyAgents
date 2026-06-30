"""colony baseline: drop ACL + add agent/skill category

Colony M0：
- 删除 project_user_access、session_members 表
- 删除 projects.access_mode 列
- 给 agents / skills 加 `category` 列（默认 'custom'），管理后台按 category 分组渲染

Revision ID: 019_colony_baseline
Revises: 018_drop_agent_render_columns
Create Date: 2026-05-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "019_colony_baseline"
down_revision: str | None = "018_drop_agent_render_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1) 删除 ACL 表 ──
    tables = set(inspector.get_table_names())
    if "session_members" in tables:
        # 同时清理 PG 上的索引（drop_table 一般会顺带 drop 索引，但保险）
        try:
            op.drop_index("ix_session_members_session_id", table_name="session_members")
        except Exception:
            pass
        try:
            op.drop_index("ix_session_members_user_id", table_name="session_members")
        except Exception:
            pass
        op.drop_table("session_members")
    if "project_user_access" in tables:
        try:
            op.drop_index(
                "ix_project_user_access_project_id", table_name="project_user_access"
            )
        except Exception:
            pass
        try:
            op.drop_index(
                "ix_project_user_access_user_id", table_name="project_user_access"
            )
        except Exception:
            pass
        op.drop_table("project_user_access")

    # ── 2) 删除 projects.access_mode 列 ──
    project_cols = {col["name"] for col in inspector.get_columns("projects")}
    if "access_mode" in project_cols:
        op.drop_column("projects", "access_mode")

    # ── 3) 给 agents 加 category ──
    agent_cols = {col["name"] for col in inspector.get_columns("agents")}
    if "category" not in agent_cols:
        op.add_column(
            "agents",
            sa.Column(
                "category",
                sa.String(length=32),
                nullable=False,
                server_default="custom",
            ),
        )
        op.create_index("ix_agents_category", "agents", ["category"])

    # ── 4) 给 skills 加 category ──
    skill_cols = {col["name"] for col in inspector.get_columns("skills")}
    if "category" not in skill_cols:
        op.add_column(
            "skills",
            sa.Column(
                "category",
                sa.String(length=32),
                nullable=False,
                server_default="custom",
            ),
        )
        op.create_index("ix_skills_category", "skills", ["category"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    skill_cols = {col["name"] for col in inspector.get_columns("skills")}
    if "category" in skill_cols:
        try:
            op.drop_index("ix_skills_category", table_name="skills")
        except Exception:
            pass
        op.drop_column("skills", "category")

    agent_cols = {col["name"] for col in inspector.get_columns("agents")}
    if "category" in agent_cols:
        try:
            op.drop_index("ix_agents_category", table_name="agents")
        except Exception:
            pass
        op.drop_column("agents", "category")

    project_cols = {col["name"] for col in inspector.get_columns("projects")}
    if "access_mode" not in project_cols:
        op.add_column(
            "projects",
            sa.Column(
                "access_mode",
                sa.String(length=16),
                nullable=False,
                server_default="public",
            ),
        )

    tables = set(inspector.get_table_names())
    if "project_user_access" not in tables:
        op.create_table(
            "project_user_access",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column(
                "project_id",
                sa.UUID(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.UUID(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "project_id", "user_id", name="uq_project_user_access"
            ),
        )
        op.create_index(
            "ix_project_user_access_project_id",
            "project_user_access",
            ["project_id"],
        )
        op.create_index(
            "ix_project_user_access_user_id",
            "project_user_access",
            ["user_id"],
        )
    if "session_members" not in tables:
        op.create_table(
            "session_members",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column(
                "session_id",
                sa.UUID(),
                sa.ForeignKey("sessions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.UUID(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "role",
                sa.String(length=16),
                nullable=False,
                server_default="member",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "session_id", "user_id", name="uq_session_user_membership"
            ),
        )
        op.create_index(
            "ix_session_members_session_id", "session_members", ["session_id"]
        )
        op.create_index(
            "ix_session_members_user_id", "session_members", ["user_id"]
        )
