"""Builder 单-项目不变量：用户 +新建 的设计会话（slug != 'builder'）里，
一个 builder 会话也只该建一个 mission；第二次 mission_create 必须复用、绝不再建。

回归 mission-df779b 真事故：设计会话 slug='mission-df779b'，Builder 在 MCP 弯路后又调了一次
agent_create+mission_create → 同一 super 出现两个 mission（小红书推广运营 / 小红书内容营销运营）
→ build_finalizer 按 project_slug 判幂等 → **弹了两张「创建完成·进入工作台」CTA**。

根因：mission_create 的复用守卫只在 `_bproj.slug == 'builder'` 时生效，漏掉了 supervisor 是
Builder（category='builder'）的用户设计会话。修法：按 supervisor.category=='builder' 判定
（与 build_finalizer 一致）。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.provider import LLMModel, LLMProvider
from app.models.user import User
from app.skills_builtin.context import BuiltinToolContext

pytestmark = pytest.mark.asyncio


async def _seed_design_session(db) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """一个用户 +新建 的 Builder 设计会话（slug != 'builder'，supervisor category='builder'）。

    Returns (design_mission_id, builder_super_id, model_id)。"""
    u = User(username=f"u-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@t.io",
             hashed_password="x")
    db.add(u)
    await db.flush()
    builder = Agent(name=f"builder-{uuid.uuid4().hex[:6]}", category="builder", kind="super",
                    model_id=None, soul_md="x", protocol_md="x")
    db.add(builder)
    await db.flush()
    # 关键：slug 不是 'builder'（模拟 +新建 的设计会话）
    proj = Mission(name="设计会话", slug=f"mission-{uuid.uuid4().hex[:6]}",
                   supervisor_agent_id=builder.id, created_by=u.id)
    db.add(proj)
    await db.flush()
    pid = uuid.uuid4()
    db.add(LLMProvider(id=pid, name=f"ds-{uuid.uuid4().hex[:5]}", provider_type="openai",
                       api_key="x", base_url="https://x"))
    mid = uuid.uuid4()
    db.add(LLMModel(id=mid, provider_id=pid, model_id="deepseek-v4-pro",
                    display_name="deepseek-v4-pro", model_type="chat"))
    await db.commit()
    return proj.id, builder.id, mid


async def test_second_mission_create_in_design_session_reuses_not_recreate(
    db_session, _patched_session_local
):
    from app.db.session import AsyncSessionLocal
    from app.skills_builtin.builder.builder_skills import (
        agent_create_tool,
        mission_create_tool,
    )

    design_mission_id, _builder_id, mid = await _seed_design_session(db_session)
    ctx = BuiltinToolContext(
        mission_id=design_mission_id,
        db_factory=AsyncSessionLocal,
        extra={"acting_user_id": str((await db_session.execute(select(User.id))).scalars().first())},
    )

    # 1) Builder 建出该会话的 super（写 built_by_mission_id=设计会话）
    sup = await agent_create_tool(ctx).coroutine(
        name=f"xhs-sup-{uuid.uuid4().hex[:5]}", model_id=str(mid), kind="super",
    )
    assert sup["ok"], sup
    sup_id = sup["agent_id"]

    # 2) 第一次 mission_create → 建出 mission A
    m1 = await mission_create_tool(ctx).coroutine(
        name="小红书推广运营", slug=f"xhs-a-{uuid.uuid4().hex[:5]}",
        supervisor_agent_id=sup_id,
    )
    assert m1["ok"] and not m1.get("reused"), m1

    # 3) 第二次 mission_create（不同名/不同 slug）→ 必须复用 A，不得新建 B
    m2 = await mission_create_tool(ctx).coroutine(
        name="小红书内容营销运营", slug=f"xhs-b-{uuid.uuid4().hex[:5]}",
        supervisor_agent_id=sup_id,
    )
    assert m2.get("reused") is True, m2
    assert m2["mission_id"] == m1["mission_id"], (m1, m2)

    # 该 super 名下只有 1 个 mission
    cnt = (await db_session.execute(
        select(func.count()).select_from(Mission).where(Mission.supervisor_agent_id == uuid.UUID(sup_id))
    )).scalar()
    assert cnt == 1, f"应只建一个 mission，实有 {cnt}"


async def test_autocreated_supervisor_protocol_is_capability_based(
    db_session, _patched_session_local
):
    """ADR-027 P1：mission_create 自动建的 super，默认协议是 capability dispatch 版
    （invoke_worker + required_capabilities），不含节点版 dispatch / mission_add_node。"""
    from app.db.session import AsyncSessionLocal
    from app.skills_builtin.builder.builder_skills import mission_create_tool

    design_mission_id, _b, mid = await _seed_design_session(db_session)
    ctx = BuiltinToolContext(
        mission_id=design_mission_id, db_factory=AsyncSessionLocal,
        extra={"acting_user_id": str((await db_session.execute(select(User.id))).scalars().first())},
    )
    res = await mission_create_tool(ctx).coroutine(
        name="cap-super", slug=f"cap-{uuid.uuid4().hex[:5]}", supervisor_model_id=str(mid),
    )
    assert res["ok"], res
    # next_steps 不再要求挂节点
    assert "mission_add_node" not in res.get("next_steps", ""), res.get("next_steps")
    # 自动建的 super 协议是 capability 版
    sup = await db_session.get(Agent, uuid.UUID(res["supervisor_agent_id"]))
    proto = (sup.protocol_md or "")
    assert "invoke_worker" in proto, proto
    assert "dispatch_to_worker" not in proto, proto
