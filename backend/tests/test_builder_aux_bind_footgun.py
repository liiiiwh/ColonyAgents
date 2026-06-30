"""封 footgun：Builder 别把 `agent_aux_model_bind` 这类 **Builder 专用工具** 当技能 skill_bind 到 worker。

Chrome e2e 实测抓到的真隐患：Builder 自主出图 worker 时，本能动作是
`skill_bind(agent_aux_model_bind, config={role,model_id})`——把一个 Builder 构建期工具当
runtime 技能绑到 worker。这是**空操作**（绑技能 ≠ 写 AgentAuxModel 行），运行时
`invoke_aux_model(role='image')` 仍「未找到辅助模型」出不了图。`agent_aux_model_bind` 是
该**直接调用**的 Builder 工具。

两条防线：
1) skill_bind 拒绝 category='builder' 的 skill，并提示「直接调用该工具」。
2) skill_list_available 默认不把 category='builder' 工具当可绑 worker 技能列出来。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.agent import Agent
from app.models.skill import Skill
from app.skills_builtin.context import BuiltinToolContext
from app.skills_builtin.builder.builder_skills import (
    skill_bind_tool,
    skill_list_available_tool,
)

pytestmark = pytest.mark.asyncio


async def _seed(db) -> uuid.UUID:
    db.add(Skill(slug="agent_aux_model_bind", name="Agent Aux Model Bind",
                 description="给 agent 绑辅助 LLM 模型", skill_type="tool_builtin",
                 category="builder", builtin_ref="agent_aux_model_bind", is_builtin=True))
    db.add(Skill(slug="invoke_aux_model", name="Invoke Aux Model",
                 description="调用辅助模型出图/出视频", skill_type="tool_builtin",
                 category="worker", builtin_ref="invoke_aux_model", is_builtin=True))
    w = Agent(name="img worker", kind="worker", capability="img_gen", model_id=None)
    db.add(w)
    await db.commit()
    return w.id


async def test_skill_bind_rejects_builder_tool(db_engine):
    """skill_bind 一个 category='builder' 的工具 → 拒绝 + 指向直接调用。"""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db:
        wid = await _seed(db)

    ctx = BuiltinToolContext(db_factory=factory)
    res = await skill_bind_tool(ctx).coroutine(
        agent_id=str(wid), skill_id="agent_aux_model_bind",
        config={"role": "image", "model_id": "323d8582"},
    )
    assert res["ok"] is False
    # 引导：错误信息必须点名该工具、提示直接调用（而非 skill_bind）
    assert "agent_aux_model_bind" in res["error"]

    # 且确实没有把这条 builder 技能绑上去
    from sqlalchemy import select
    from app.models.agent import AgentSkill
    async with factory() as db:
        rows = (await db.execute(select(AgentSkill).where(AgentSkill.agent_id == wid))).scalars().all()
        assert rows == []


async def test_skill_bind_allows_normal_worker_skill(db_engine):
    """普通 worker 技能（category!='builder'）照常可绑。"""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db:
        wid = await _seed(db)

    ctx = BuiltinToolContext(db_factory=factory)
    res = await skill_bind_tool(ctx).coroutine(agent_id=str(wid), skill_id="invoke_aux_model")
    assert res["ok"] is True


async def test_skill_bind_rejects_aux_config_stuffing(db_engine):
    """更宽的 footgun：把 aux 模型绑定塞进**任意** skill 的 config（哪怕是 worker 技能
    invoke_aux_model / parallel_invoke_aux_model）也是空操作——skill config 不是 AgentAuxModel。
    必须拒绝并指向直接调用 agent_aux_model_bind。"""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db:
        wid = await _seed(db)

    ctx = BuiltinToolContext(db_factory=factory)
    # 形态 1：config 里带 aux_models
    res1 = await skill_bind_tool(ctx).coroutine(
        agent_id=str(wid), skill_id="invoke_aux_model",
        config={"aux_models": [{"role": "image", "model_id": "doubao-seedream-5-0-260128"}]},
    )
    assert res1["ok"] is False
    assert "agent_aux_model_bind" in res1["error"]

    # 形态 2：config 里带 model_id + role（出图/视频/embedding 角色）
    res2 = await skill_bind_tool(ctx).coroutine(
        agent_id=str(wid), skill_id="parallel_invoke_aux_model",
        config={"role": "image", "model_id": "323d8582"},
    )
    assert res2["ok"] is False
    assert "agent_aux_model_bind" in res2["error"]

    # 没有任何绑定落到 agent_skills（被前置拒绝）
    from sqlalchemy import select
    from app.models.agent import AgentSkill
    async with factory() as db:
        rows = (await db.execute(select(AgentSkill).where(AgentSkill.agent_id == wid))).scalars().all()
        assert rows == []


async def test_skill_list_available_excludes_builder_tools(db_engine):
    """skill_list_available 默认不暴露 builder 工具为可绑技能（避免诱导 skill_bind）。"""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db:
        await _seed(db)

    ctx = BuiltinToolContext(db_factory=factory)
    res = await skill_list_available_tool(ctx).coroutine(query="aux")
    slugs = [i["slug"] for i in res["items"]]
    assert "invoke_aux_model" in slugs
    assert "agent_aux_model_bind" not in slugs
