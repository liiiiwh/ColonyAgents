"""ADR-009 G2 修补 · project_escalations.category 放开 'worker_health'。

report_worker_issue 用 category='worker_health' 上报「现有 worker 坏了」，但建表时的
ck_pe_category CHECK 只允许 structural/resource/strategy_pivot/stuck → INSERT 违反约束、
super 上报 worker 问题时 tick 崩。这里把 worker_health 加进 CHECK。
"""
from __future__ import annotations

from alembic import op


revision = "053_worker_health_category"
down_revision = "052_adr009_builder_governance"
branch_labels = None
depends_on = None

_OLD = "category IN ('structural','resource','strategy_pivot','stuck')"
_NEW = "category IN ('structural','resource','strategy_pivot','stuck','worker_health')"


def upgrade() -> None:
    op.drop_constraint("ck_pe_category", "project_escalations", type_="check")
    op.create_check_constraint("ck_pe_category", "project_escalations", _NEW)


def downgrade() -> None:
    op.drop_constraint("ck_pe_category", "project_escalations", type_="check")
    op.create_check_constraint("ck_pe_category", "project_escalations", _OLD)
