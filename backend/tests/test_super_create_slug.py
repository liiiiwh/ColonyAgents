"""M2/agent_create 路径建 super 也要落 slug + display_name（apply_super_spec 已设；
create_agent 之前漏了 → M2 建出的 super slug/display_name 为空，路由/标题只能回退 agent 名）。
"""
import pytest

from app.schemas.agent import AgentCreate
from app.services.agent_service import create_agent


@pytest.mark.asyncio
async def test_create_super_derives_slug_and_display_name(db_session):
    agent = await create_agent(db_session, AgentCreate(
        name="Server Ops Monitor Super", kind="super", category="custom",
    ))
    assert agent.slug == "server-ops-monitor-super"
    assert agent.display_name == "Server Ops Monitor Super"


@pytest.mark.asyncio
async def test_create_super_slug_unique_suffix(db_session):
    a1 = await create_agent(db_session, AgentCreate(name="Dup Super", kind="super", category="custom"))
    a2 = await create_agent(db_session, AgentCreate(name="Dup Super 2", kind="super", category="custom"))
    # 不同 name 但 sluggify 后若冲突需加后缀；这里 name 不同，slug 也不同
    assert a1.slug != a2.slug
    assert a1.slug and a2.slug


@pytest.mark.asyncio
async def test_super_slug_hint_overrides_chinese_name(db_session):
    """中文 display_name 的 super：slug 应取 slug_hint（url-safe mission slug 派生），
    而非从中文 name slugify 退化成无语义的裸 'supervisor'。"""
    agent = await create_agent(db_session, AgentCreate(
        name="电商客服工单处理 · Supervisor", kind="super", category="custom",
    ), slug_hint="ecom-ticket-processor-supervisor")
    assert agent.slug == "ecom-ticket-processor-supervisor"
    assert agent.display_name == "电商客服工单处理 · Supervisor"


@pytest.mark.asyncio
async def test_super_slug_hint_unique_suffix(db_session):
    """两个不同领域但 hint 撞车 → 第二个加后缀，不冲突唯一约束。"""
    a1 = await create_agent(db_session, AgentCreate(name="甲 · Supervisor", kind="super", category="custom"),
                            slug_hint="ops-supervisor")
    a2 = await create_agent(db_session, AgentCreate(name="乙 · Supervisor", kind="super", category="custom"),
                            slug_hint="ops-supervisor")
    assert a1.slug == "ops-supervisor"
    assert a2.slug == "ops-supervisor-2"


@pytest.mark.asyncio
async def test_create_worker_no_slug(db_session):
    """worker 不需要 super 身份 slug。"""
    agent = await create_agent(db_session, AgentCreate(
        name="Some Worker", kind="worker", category="worker.data", capability="data_x",
    ))
    assert agent.slug is None
