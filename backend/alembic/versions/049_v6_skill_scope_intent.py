"""v6 Bonus · Skill.scope + Skill.intent (CONTEXT.md > Skill 维度)。

让 agent_service.auto_bind 不再硬编码 DEFAULT_AUTO_BIND_SKILL_EXCLUDE，
而能 query "scope IN (agent.kind, 'all')"。

nullable=True 兼容老数据；migration 后跑 backfill_skill_scope.py 给 32 个
builtin skill 一次性塞 scope/intent（不打 NULL 漏写者自动 fallback all + io）。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "049_v6_skill_scope_intent"
down_revision = "048_v6_l2_relax_branch_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("scope", sa.String(16), nullable=True))
    op.add_column("skills", sa.Column("intent", sa.String(32), nullable=True))
    op.create_index("ix_skills_scope", "skills", ["scope"])
    op.create_index("ix_skills_intent", "skills", ["intent"])

    # backfill 已知 super-only 的内置 skill —— 后续 agent_service.auto_bind 可读
    op.execute("""
        UPDATE skills SET scope='super', intent='dispatch'
         WHERE slug IN ('invoke_worker','invoke_workers_parallel','list_workers',
                        'request_new_capability','list_supers',
                        'emit_redirect_suggestion','request_approval',
                        'request_structured_input',
                        'agent_protocol_propose','agent_protocol_apply',
                        'agent_protocol_revert','agent_protocol_evaluate',
                        'output_quality_check_force_override',
                        'project_escalate_to_builder','project_escalation_dismiss',
                        'project_escalation_list',
                        'dispatch_to_worker','parallel_dispatch')
    """)
    op.execute("""
        UPDATE skills SET scope='super', intent='memory'
         WHERE slug IN ('archive_to_knowledge','experience_record',
                        'rollback_to_node','set_branch_description')
    """)
    op.execute("""
        UPDATE skills SET scope='worker', intent='io'
         WHERE slug IN ('return_result','wechat_push_notification')
    """)
    op.execute("""
        UPDATE skills SET scope='builder', intent='dispatch'
         WHERE category='builder' AND scope IS NULL
    """)
    # 兜底：未标 scope 的全 'all'，intent 默认 'io'
    op.execute("UPDATE skills SET scope='all' WHERE scope IS NULL")
    op.execute("UPDATE skills SET intent='io' WHERE intent IS NULL")


def downgrade() -> None:
    op.drop_index("ix_skills_intent", table_name="skills")
    op.drop_index("ix_skills_scope", table_name="skills")
    op.drop_column("skills", "intent")
    op.drop_column("skills", "scope")
