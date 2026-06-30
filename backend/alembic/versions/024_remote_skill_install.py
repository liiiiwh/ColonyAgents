"""M6: remote_skill_install table (ClawHub installed skill state)

Revision ID: 024_remote_skill_install
Revises: 023_session_scope
Create Date: 2026-05-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "024_remote_skill_install"
down_revision: str | None = "023_session_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "remote_skill_install" in set(inspector.get_table_names()):
        return
    op.create_table(
        "remote_skill_install",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "project_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("clawhub_slug", sa.String(length=255), nullable=False),
        sa.Column("clawhub_version", sa.String(length=64), nullable=False),
        sa.Column("runtime_kind", sa.String(length=32), nullable=False),
        sa.Column("install_dir", sa.String(length=512), nullable=False),
        sa.Column("entrypoint", sa.String(length=512), nullable=True),
        sa.Column("python_wrapper_path", sa.String(length=512), nullable=True),
        sa.Column(
            "capability_tags", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "security_summary", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "installed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "local_skill_id",
            sa.UUID(),
            sa.ForeignKey("skills.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "clawhub_slug", "clawhub_version", name="uq_remote_skill_slug_version"
        ),
    )
    op.create_index(
        "ix_remote_skill_install_project_id",
        "remote_skill_install",
        ["project_id"],
    )
    op.create_index(
        "ix_remote_skill_install_clawhub_slug",
        "remote_skill_install",
        ["clawhub_slug"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "remote_skill_install" not in set(inspector.get_table_names()):
        return
    for idx in (
        "ix_remote_skill_install_clawhub_slug",
        "ix_remote_skill_install_project_id",
    ):
        try:
            op.drop_index(idx, table_name="remote_skill_install")
        except Exception:
            pass
    op.drop_table("remote_skill_install")
