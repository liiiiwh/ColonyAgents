"""L3：project_escalations 表

Revision ID: 037_project_escalations
Revises: 036_project_origin_session
Create Date: 2026-05-23
"""

from __future__ import annotations

from alembic import op

revision: str = "037_project_escalations"
down_revision: str | None = "036_project_origin_session"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS project_escalations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            category VARCHAR(32) NOT NULL,
            severity VARCHAR(16) NOT NULL DEFAULT 'warn',
            summary VARCHAR(280) NOT NULL,
            evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            proposed_change VARCHAR(2000) NOT NULL DEFAULT '',
            fingerprint VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            delivered_at TIMESTAMP WITH TIME ZONE NULL,
            target_session_id UUID NULL REFERENCES sessions(id) ON DELETE SET NULL,
            resolution_summary TEXT NULL,
            resolved_at TIMESTAMP WITH TIME ZONE NULL,
            resolved_by VARCHAR(128) NULL,
            CONSTRAINT ck_pe_category CHECK (category IN ('structural','resource','strategy_pivot','stuck')),
            CONSTRAINT ck_pe_severity CHECK (severity IN ('info','warn','critical')),
            CONSTRAINT ck_pe_status CHECK (status IN ('pending','delivered','acted','dismissed','superseded'))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pe_project_created ON project_escalations(project_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pe_fingerprint ON project_escalations(fingerprint)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pe_status ON project_escalations(status) "
        "WHERE status IN ('pending','delivered')"
    )
    # 关键 unique：同项目同 fingerprint 同 UTC 日 最多 1 行（H3 dedup）
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pe_project_fp_day "
        "ON project_escalations(project_id, fingerprint, ((created_at AT TIME ZONE 'UTC')::date))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_pe_project_fp_day")
    op.execute("DROP INDEX IF EXISTS ix_pe_status")
    op.execute("DROP INDEX IF EXISTS ix_pe_fingerprint")
    op.execute("DROP INDEX IF EXISTS ix_pe_project_created")
    op.execute("DROP TABLE IF EXISTS project_escalations")
