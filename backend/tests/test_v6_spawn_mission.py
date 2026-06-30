"""v6.A · spawn_mission tracer.

Mission = 既有 super 的一次实例化。spawn_mission(super_agent_id, name)
创建一个新 Mission (= Mission)，复用既有 SuperAgent；不新建 agent，不要求
goal_spec（goal 由首次 user msg → super tick → request_structured_input 收）。

公共接口：
    spawn_mission(db, super_agent_id, name, created_by, goal_hint?) → MissionRef
        MissionRef.mission_id, .super_agent_id, .slug
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def db_session():
    """sqlite + 必需表子集（绕 JSONB-only model）；返回单 AsyncSession。"""
    from app.db.base import Base
    import app.models.user  # noqa
    import app.models.provider  # noqa
    import app.models.agent  # noqa
    import app.models.skill  # noqa
    import app.models.mission  # noqa

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for tname in (
            "users", "llm_providers", "llm_models",
            "skills", "mcp_servers",
            "agents", "agent_skills", "agent_mcp_servers", "agent_aux_models",
            "missions", "mission_run_state", "mission_nodes",
        ):
            tbl = Base.metadata.tables.get(tname)
            if tbl is not None:
                try:
                    await conn.run_sync(tbl.create)
                except Exception:
                    pass
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def super_agent_seed(db_session):
    """准备一个 super agent + admin user 给 spawn_mission 用。"""
    from app.models.agent import Agent
    from app.models.user import User

    user_id = uuid.uuid4()
    super_id = uuid.uuid4()
    db_session.add(User(
        id=user_id, username=f"u_{user_id.hex[:6]}", email=f"u-{user_id.hex[:6]}@x.com",
        hashed_password="x", role="admin", is_active=True,
    ))
    db_session.add(Agent(
        id=super_id, name=f"sup_{super_id.hex[:6]}", kind="super",
        category="custom", model_id=uuid.uuid4(),
        soul_md="", protocol_md="",
    ))
    await db_session.commit()
    return {"user_id": user_id, "super_id": super_id, "db": db_session}


@pytest.mark.asyncio
async def test_spawn_mission_creates_project_referencing_super(super_agent_seed):
    """Tracer #1：spawn_mission 创建 Mission，不新建 Agent。"""
    from app.models.agent import Agent
    from app.models.mission import Mission
    from app.domain.builder.factory import spawn_mission
    from sqlalchemy import select, func

    user_id = super_agent_seed["user_id"]
    super_id = super_agent_seed["super_id"]
    db = super_agent_seed["db"]

    ref = await spawn_mission(
        db, super_agent_id=super_id, name="小米粉丝运营", created_by=user_id,
    )

    assert ref.super_agent_id == super_id
    assert ref.slug
    agent_count = (await db.execute(select(func.count()).select_from(Agent))).scalar()
    assert agent_count == 1, "spawn_mission 不应该新建 agent"
    proj = await db.get(Mission, ref.mission_id)
    assert proj.supervisor_agent_id == super_id
    assert proj.name == "小米粉丝运营"
    assert proj.created_by == user_id


@pytest.mark.asyncio
async def test_spawn_mission_with_goal_hint_writes_workflow_config(super_agent_seed):
    """Tracer #2：goal_hint 写入 project.workflow_config.goal_hint。"""
    from app.models.mission import Mission
    from app.domain.builder.factory import spawn_mission

    db = super_agent_seed["db"]
    ref = await spawn_mission(
        db, super_agent_id=super_agent_seed["super_id"],
        name="实验账号", created_by=super_agent_seed["user_id"],
        goal_hint="测试新 hook 公式，看哪个互动率高",
    )
    proj = await db.get(Mission, ref.mission_id)
    assert proj.workflow_config.get("goal_hint") == "测试新 hook 公式，看哪个互动率高"


@pytest.mark.asyncio
async def test_spawn_mission_two_missions_same_super_distinct_projects(super_agent_seed):
    """Tracer #3：同 super spawn 2 个 mission → 不同 mission_id 和 slug。"""
    from app.models.mission import Mission
    from app.domain.builder.factory import spawn_mission
    from sqlalchemy import select, func

    db = super_agent_seed["db"]
    sid = super_agent_seed["super_id"]
    uid = super_agent_seed["user_id"]
    ref_a = await spawn_mission(db, super_agent_id=sid, name="账号 A", created_by=uid)
    ref_b = await spawn_mission(db, super_agent_id=sid, name="账号 B", created_by=uid)
    assert ref_a.mission_id != ref_b.mission_id
    assert ref_a.slug != ref_b.slug
    cnt = (await db.execute(
        select(func.count()).select_from(Mission).where(Mission.supervisor_agent_id == sid)
    )).scalar()
    assert cnt == 2


@pytest.mark.asyncio
async def test_spawn_mission_defaults_auto_approve_true_when_super_unset(super_agent_seed):
    """ADR-026 D1：super 未设 extra_config.mission_default_auto_approve → 新 mission 缺省全自动 True。"""
    from app.models.mission import Mission
    from app.domain.builder.factory import spawn_mission

    db = super_agent_seed["db"]
    ref = await spawn_mission(
        db, super_agent_id=super_agent_seed["super_id"],
        name="默认全自动", created_by=super_agent_seed["user_id"],
    )
    proj = await db.get(Mission, ref.mission_id)
    assert proj.auto_approve is True


@pytest.mark.asyncio
async def test_spawn_mission_honors_super_default_false(super_agent_seed):
    """ADR-026 D1/D2：super.extra_config.mission_default_auto_approve=False（如 Builder）→
    该 super 新建的 mission 快照为 auto_approve=False。"""
    from app.models.agent import Agent
    from app.models.mission import Mission
    from app.domain.builder.factory import spawn_mission

    db = super_agent_seed["db"]
    sup = await db.get(Agent, super_agent_seed["super_id"])
    sup.extra_config = {"mission_default_auto_approve": False}
    await db.commit()

    ref = await spawn_mission(
        db, super_agent_id=super_agent_seed["super_id"],
        name="人审 super", created_by=super_agent_seed["user_id"],
    )
    proj = await db.get(Mission, ref.mission_id)
    assert proj.auto_approve is False


@pytest.mark.asyncio
async def test_spawn_mission_honors_super_default_true_explicit(super_agent_seed):
    """ADR-026 D1：super 显式设 True 也走全自动（与缺省一致，验证读到了配置值）。"""
    from app.models.agent import Agent
    from app.models.mission import Mission
    from app.domain.builder.factory import spawn_mission

    db = super_agent_seed["db"]
    sup = await db.get(Agent, super_agent_seed["super_id"])
    sup.extra_config = {"mission_default_auto_approve": True}
    await db.commit()

    ref = await spawn_mission(
        db, super_agent_id=super_agent_seed["super_id"],
        name="显式全自动", created_by=super_agent_seed["user_id"],
    )
    proj = await db.get(Mission, ref.mission_id)
    assert proj.auto_approve is True


@pytest.mark.asyncio
async def test_spawn_mission_rejects_non_super_agent(db_session):
    """Tracer #4：传入 kind=worker 的 agent → ValueError。"""
    from app.models.agent import Agent
    from app.models.user import User
    from app.domain.builder.factory import spawn_mission

    user_id = uuid.uuid4()
    worker_id = uuid.uuid4()
    db_session.add(User(id=user_id, username="u_w", email="u_w@x.com",
                        hashed_password="x", role="admin", is_active=True))
    db_session.add(Agent(id=worker_id, name="xhs_worker_t", kind="worker",
                         capability="xhs_ops", category="worker.custom",
                         model_id=uuid.uuid4(), soul_md="", protocol_md=""))
    await db_session.commit()
    with pytest.raises(ValueError, match="kind.*super"):
        await spawn_mission(db_session, super_agent_id=worker_id, name="x", created_by=user_id)
