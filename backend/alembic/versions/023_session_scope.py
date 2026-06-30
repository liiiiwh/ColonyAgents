"""M4: sessions.scope column (orchestrator / observation_legacy)

Existing rows default to 'observation_legacy'（保留可读，UI 不再暴露）；
之后新建的 session 默认 'orchestrator'。

Revision ID: 023_session_scope
Revises: 022_project_agent_memory
Create Date: 2026-05-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "023_session_scope"
down_revision: str | None = "022_project_agent_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("sessions")}
    if "scope" in cols:
        return
    op.add_column(
        "sessions",
        sa.Column(
            "scope",
            sa.String(length=24),
            nullable=False,
            server_default="observation_legacy",
        ),
    )
    op.create_index("ix_sessions_scope", "sessions", ["scope"])
    # 把 server_default 改回 'orchestrator'（之后新行默认这个值；已有 server_default
    # 是为了一次性给历史行回填）。
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "sessions", "scope", server_default="orchestrator"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("sessions")}
    if "scope" not in cols:
        return
    try:
        op.drop_index("ix_sessions_scope", table_name="sessions")
    except Exception:
        pass
    op.drop_column("sessions", "scope")
