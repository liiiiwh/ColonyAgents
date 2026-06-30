"""Builder opened_by 死路由修复：用户新开 builder mission（带 goal_hint）时，
prompt 注入「DESIGN_SUPER 会话 + 用户需求」块，让 builder 按真实领域设计 super，
不再当空项目、不再套用小红书 legacy 模板。
"""
import uuid

import pytest

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.services.agent_service import assemble_system_prompt_async
from app.skills_builtin.context import BuiltinToolContext


@pytest.mark.asyncio
async def test_builder_prompt_injects_user_design_brief(db_session):
    user = User(username="u", email="u@x.com", hashed_password="x", role="admin")
    db_session.add(user)
    agent = Agent(name="Builder Supervisor", category="builder", kind="super",
                  soul_md="soul", protocol_md="proto")
    db_session.add(agent)
    await db_session.flush()
    m = Mission(name="eval-devops", slug="eval-devops", supervisor_agent_id=agent.id,
                created_by=user.id,
                workflow_config={"goal_hint": "设计一个『服务器运维监控』super，配好 worker 与调度"})
    db_session.add(m)
    await db_session.commit()

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    agent = (await db_session.execute(
        select(Agent).options(selectinload(Agent.skills)).where(Agent.id == agent.id)
    )).scalar_one()
    ctx = BuiltinToolContext(agent_node_name="supervisor", mission_id=m.id, memory_scope="project")
    prompt = await assemble_system_prompt_async(db_session, agent, ctx)

    assert "服务器运维监控" in prompt           # 用户真实需求被注入
    assert "DESIGN_SUPER" in prompt              # 明确进设计模式
    assert "opened_by=user" in prompt


@pytest.mark.asyncio
async def test_builder_brief_anchors_from_first_user_message_when_no_goal_hint(db_session):
    """chat 路径无 goal_hint：brief 从主线首条用户消息取需求，并带强反漂移指令，
    让 builder 整条 M2 管道都锚在这个领域，不漂到 HR/小红书等示例。"""
    from app.services import messaging_service as _msg
    user = User(username="u3", email="u3@x.com", hashed_password="x", role="admin")
    db_session.add(user)
    agent = Agent(name="Builder Supervisor", category="builder", kind="super",
                  soul_md="s", protocol_md="p")
    db_session.add(agent)
    await db_session.flush()
    m = Mission(name="Colony Builder", slug="builder", supervisor_agent_id=agent.id,
                created_by=user.id, workflow_config={})  # 无 goal_hint
    db_session.add(m)
    await db_session.commit()
    await _msg.append_message(db_session, m.id, "main", role="user",
                             content="我要一个『服务器运维监控』助理，巡检健康指标")
    await db_session.commit()

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    agent = (await db_session.execute(
        select(Agent).options(selectinload(Agent.skills)).where(Agent.id == agent.id)
    )).scalar_one()
    ctx = BuiltinToolContext(agent_node_name="supervisor", mission_id=m.id, memory_scope="project")
    prompt = await assemble_system_prompt_async(db_session, agent, ctx)
    assert "服务器运维监控" in prompt           # 从首条用户消息锚定
    assert "DESIGN_SUPER" in prompt
    assert "每一步" in prompt or "每个构建步骤" in prompt  # 强反漂移：贯穿所有 M2 步骤


@pytest.mark.asyncio
async def test_non_builder_super_has_no_design_brief(db_session):
    """普通 super（非 builder）不注入设计简报（它不是来设计别的 super 的）。"""
    user = User(username="u2", email="u2@x.com", hashed_password="x", role="admin")
    db_session.add(user)
    agent = Agent(name="运维监控 super", category="custom", kind="super",
                  slug="server-monitor", soul_md="s", protocol_md="p")
    db_session.add(agent)
    await db_session.flush()
    m = Mission(name="run1", slug="run1", supervisor_agent_id=agent.id, created_by=user.id,
                workflow_config={"goal_hint": "巡检服务器"})
    db_session.add(m)
    await db_session.commit()
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    agent = (await db_session.execute(
        select(Agent).options(selectinload(Agent.skills)).where(Agent.id == agent.id)
    )).scalar_one()
    ctx = BuiltinToolContext(agent_node_name="supervisor", mission_id=m.id, memory_scope="project")
    prompt = await assemble_system_prompt_async(db_session, agent, ctx)
    assert "DESIGN_SUPER" not in prompt

@pytest.mark.asyncio
async def test_builder_standby_when_super_already_built(db_session):
    """builder 设计会话已建出 super → 注入「待命」、不再提案/重建（防被 tick 重入重复提案）。
    但会话保活（super 升级回投入口），仅升级时进 DESIGN_WORKER。"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    user = User(username="u4", email="u4@x.com", hashed_password="x", role="admin")
    builder_agent = Agent(name="Builder Supervisor", category="builder", kind="super",
                          slug="builder", display_name="Colony Builder", soul_md="s", protocol_md="p")
    db_session.add_all([user, builder_agent])
    await db_session.flush()
    design = Mission(name="在线教学辅导", slug="mission-edu", supervisor_agent_id=builder_agent.id,
                     created_by=user.id, workflow_config={"goal_hint": "设计教学辅导 super"})
    db_session.add(design)
    await db_session.flush()
    built = Agent(name="tutoring-supervisor", kind="super", category="custom",
                  slug="tutoring", display_name="在线教学辅导助理", built_by_mission_id=design.id)
    db_session.add(built)
    await db_session.commit()

    agent = (await db_session.execute(
        select(Agent).options(selectinload(Agent.skills)).where(Agent.id == builder_agent.id)
    )).scalar_one()
    ctx = BuiltinToolContext(agent_node_name="supervisor", mission_id=design.id, memory_scope="project")
    prompt = await assemble_system_prompt_async(db_session, agent, ctx)
    assert "待命" in prompt                       # 进入待命
    assert "在线教学辅导助理" in prompt            # 点名已建的 super
    assert "DESIGN_SUPER" not in prompt           # 不再走提案
    assert "DESIGN_WORKER" in prompt              # 仅升级时处理
