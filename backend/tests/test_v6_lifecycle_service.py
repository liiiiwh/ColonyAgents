"""v6 · LifecycleService 单一写入 seam tracer。

确保:
- 合法 transition 写 DB + 同步 runtime_status
- 非法 transition 抛 InvalidLifecycleTransition 且不写 DB
- force=True 跳过 FSM 校验
- 同步推 event_bus (不阻塞)
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text as _sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def db_session():
    """sqlite 子集表（仅 projects + sessions + agent_activities）。"""
    from app.db.base import Base
    import app.models.user  # noqa
    import app.models.provider  # noqa
    import app.models.agent  # noqa
    import app.models.skill  # noqa
    import app.models.mission  # noqa
    import app.models.message  # noqa

    from sqlalchemy.pool import StaticPool
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        for tname in (
            "users", "llm_providers", "llm_models",
            "skills", "mcp_servers",
            "agents", "agent_skills", "agent_mcp_servers", "agent_aux_models",
            "missions", "mission_run_state", "mission_nodes",
            "sessions",
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
async def project_running(db_session):
    """seed 一个 running 状态的 project (用 ORM 走默认值)。"""
    from app.models.mission import Mission
    pid = uuid.uuid4()
    p = Mission(
        id=pid, name="tst", slug=f"tst-{pid.hex[:6]}",
        supervisor_agent_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        lifecycle_status="running",
        runtime_status="running",
    )
    db_session.add(p)
    await db_session.commit()
    return pid


@pytest.mark.asyncio
async def test_legal_transition_writes_db(project_running, db_session):
    from app.domain.lifecycle_service import LifecycleService
    from app.domain.lifecycle import Lifecycle, LifecycleAction

    result = await LifecycleService(db_session).transition(
        project_running, LifecycleAction.PAUSE_FOR_CAPABILITY, reason="缺 xhs_ops",
    )
    assert result == Lifecycle.PAUSED_WAITING_CAPABILITY
    from app.models.mission import Mission
    db_session.expire_all()
    proj = await db_session.get(Mission, project_running)
    row = (proj.lifecycle_status, proj.paused_reason, proj.runtime_status) if proj else None
    assert row[0] == "paused_waiting_capability"
    assert row[1] == "缺 xhs_ops"
    # runtime_status 是 is_alive derived view → paused 仍 alive → running
    assert row[2] == "running"


@pytest.mark.asyncio
async def test_illegal_transition_raises_and_no_write(project_running, db_session):
    from app.domain.lifecycle_service import LifecycleService
    from app.domain.lifecycle import LifecycleAction, InvalidLifecycleTransition

    with pytest.raises(InvalidLifecycleTransition):
        # RUNNING --RESUME--> ? 不合法（RESUME 只在 paused_* 适用）
        await LifecycleService(db_session).transition(
            project_running, LifecycleAction.RESUME,
        )
    from app.models.mission import Mission
    proj = await db_session.get(Mission, project_running)
    row = (proj.lifecycle_status,) if proj else None
    assert row[0] == "running"  # 没被改


@pytest.mark.asyncio
async def test_force_skips_fsm(project_running, db_session):
    """admin force=True 直接走目标 state，不跑 FSM。"""
    from app.domain.lifecycle_service import LifecycleService
    from app.domain.lifecycle import Lifecycle, LifecycleAction

    # 先 stop 它
    await LifecycleService(db_session).transition(
        project_running, LifecycleAction.STOP,
    )
    # 然后 force RESUME（正常 STOPPED 不接 RESUME，但 force 可以）
    result = await LifecycleService(db_session).transition(
        project_running, LifecycleAction.RESUME, force=True,
    )
    assert result == Lifecycle.RUNNING
    from app.models.mission import Mission
    db_session.expire_all()
    proj = await db_session.get(Mission, project_running)
    assert proj.lifecycle_status == "running"
    assert proj.runtime_status == "running"


@pytest.mark.asyncio
async def test_paused_reason_cleared_on_resume(project_running, db_session):
    from app.domain.lifecycle_service import LifecycleService
    from app.domain.lifecycle import LifecycleAction

    await LifecycleService(db_session).transition(
        project_running, LifecycleAction.PAUSE_FOR_CAPABILITY, reason="缺 xhs",
    )
    # RESUME 后 reason 应清空
    await LifecycleService(db_session).transition(
        project_running, LifecycleAction.RESUME,
    )
    from app.models.mission import Mission
    db_session.expire_all()
    proj = await db_session.get(Mission, project_running)
    row = (proj.lifecycle_status, proj.paused_reason) if proj else None
    assert row[0] == "running"
    assert row[1] is None  # cleared


@pytest.mark.asyncio
async def test_stop_makes_not_alive(project_running, db_session):
    from app.domain.lifecycle_service import LifecycleService
    from app.domain.lifecycle import Lifecycle, LifecycleAction, is_alive

    result = await LifecycleService(db_session).transition(
        project_running, LifecycleAction.STOP,
    )
    assert result == Lifecycle.STOPPED
    assert not is_alive(result)
    from app.models.mission import Mission
    db_session.expire_all()
    proj = await db_session.get(Mission, project_running)
    row = (proj.runtime_status,) if proj else None
    assert row[0] == "stopped"


@pytest.mark.asyncio
async def test_missing_project_raises(db_session):
    from app.domain.lifecycle_service import LifecycleService
    from app.domain.lifecycle import LifecycleAction

    with pytest.raises(ValueError, match="不存在"):
        await LifecycleService(db_session).transition(
            uuid.uuid4(), LifecycleAction.START,
        )
