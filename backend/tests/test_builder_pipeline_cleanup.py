"""构建管线清理：删掉死的 M2 工厂 worker + 收敛 Builder 协议 + 给 Builder 真能调的绑定工具。

背景（2026-06-28 摸清）：Builder 有两套构建实现并存——用户实走的 v3 DESIGN_SUPER 手搓路径，
和一套永远触发不到的 legacy M2 8-worker 工厂管线（design_agents/provision_agents/… 12 个僵尸 worker）。
死管线把唯一可靠的图像绑定逻辑埋在用户够不到的分支里；而 Builder Supervisor 自己只有
agent_create/agent_update，没有 agent_aux_model_bind → 绑图只能走 agent_update
(capability_contract) 静默跳过路径 → 出不了图。

这条测试钉死清理后的不变式：
1. seed 后平台**不再有**那 12 个死工厂 worker（按 capability 判定）。
2. Builder Supervisor 仍在、是 super。
3. Builder Supervisor **绑了 agent_aux_model_bind 工具**（这样协议里的"出图 worker 必绑"才执行得了）。
4. Builder 协议**不再引用**死的 M2 工厂管线 / builder_assembler 派发。
5. Builder super 不再有 standing mission（ADR-027 · mission_nodes 已退役，无节点可查）。
"""
from __future__ import annotations

import pytest
from sqlalchemy import text as _sql_text

from app.db.init_db import seed_admin_user, seed_builder_project

DEAD_CAPS = {
    "design_agents", "design_pipeline", "design_supervisor", "provision_agents",
    "builder_assembler", "builder_planner", "assemble_project", "postflight_verify",
    "gather_requirements", "project_context_init", "installer", "tester",
}


@pytest.mark.asyncio
async def test_builder_pipeline_is_consolidated_and_clean(db_session):
    await seed_admin_user(db_session)
    await seed_builder_project(db_session)

    # 1. 死工厂 worker 全没了
    caps = {
        r[0]
        for r in (
            await db_session.execute(
                _sql_text("select capability from agents where kind='worker'")
            )
        ).all()
    }
    leaked = caps & DEAD_CAPS
    assert not leaked, f"死工厂 worker 仍被 seed：{leaked}"

    # 2 + 3. Builder Supervisor 在、是 super、绑了 agent_aux_model_bind
    sup = (
        await db_session.execute(
            _sql_text(
                "select id, kind, protocol_md from agents where name='Builder Supervisor'"
            )
        )
    ).first()
    assert sup is not None and sup[1] == "super"
    sup_id, _, proto = sup

    sup_skill_slugs = {
        r[0]
        for r in (
            await db_session.execute(
                _sql_text(
                    "select s.slug from agent_skills a join skills s on s.id=a.skill_id "
                    "where a.agent_id=:aid"
                ),
                {"aid": sup_id},
            )
        ).all()
    }
    assert "agent_aux_model_bind" in sup_skill_slugs, (
        "Builder Supervisor 必须能直接调 agent_aux_model_bind 才绑得上图像模型"
    )

    # 4. 协议不再引用死管线
    for dead in ("builder_assembler", "M2 BUILDER FACTORY", "design_agents"):
        assert dead not in proto, f"Builder 协议仍引用死管线：{dead!r}"

    # 5. Builder super 不再有 standing mission（设计会话由用户 +新建 按需创建）。
    #    ADR-027：mission_nodes 表已退役，原「Builder mission 不再挂死工厂节点」断言取消。
    builder_mission_count = (
        await db_session.execute(
            _sql_text("select count(*) from missions where slug='builder'")
        )
    ).scalar()
    assert builder_mission_count == 0, (
        "Builder super 不应有 standing mission（slug='builder'）；设计会话按需创建"
    )
