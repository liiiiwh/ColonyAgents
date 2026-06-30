"""R2-3 · MemoryReader · 3-tier 统一读路径 tracer。

3 层（CONTEXT.md）：
  - MissionMemory: mission_agent_memory.memory_md
  - SuperMemory:   agents.domain_memory_md
  - PlatformKB:    knowledge_bases scope='platform' (这里只测前 2 层；KB 走 knowledge_search 单独)
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def db_session():
    from app.db.base import Base
    import app.models.user  # noqa
    import app.models.provider  # noqa
    import app.models.agent  # noqa
    import app.models.skill  # noqa
    import app.models.mission  # noqa
    import app.models.message  # noqa

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
            "mission_agent_memory",
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
async def super_and_mission(db_session):
    """seed 一个 super agent (有 domain_memory_md) + 一个 mission (mission_agent_memory)。"""
    from app.models.agent import Agent
    from app.models.provider import LLMProvider, LLMModel
    from app.models.mission import Mission

    pid = uuid.uuid4()
    db_session.add(LLMProvider(
        id=pid, name="p", provider_type="custom",
        api_key="x", base_url="https://x",
    ))
    mid = uuid.uuid4()
    db_session.add(LLMModel(
        id=mid, provider_id=pid, model_id="m", display_name="m", model_type="chat",
    ))
    sup_id = uuid.uuid4()
    db_session.add(Agent(
        id=sup_id, name="sup", kind="super", category="custom", model_id=mid,
        soul_md="", protocol_md="",
        domain_memory_md="超角色长期记忆：xhs 规则 / 平台共识 etc.",
    ))
    mission_id = uuid.uuid4()
    db_session.add(Mission(
        id=mission_id, name="m1", slug="m1",
        supervisor_agent_id=sup_id,
        created_by=uuid.uuid4(),
    ))
    await db_session.commit()
    # seed mission memory
    from app.services import memory_service
    await memory_service.upsert_project_memory(
        db_session, mission_id, "supervisor",
        "Mission-level: 已发布 5 条，最近表现 ↑",
        compressed_count=3,
    )
    return {"super_id": sup_id, "mission_id": mission_id}


@pytest.mark.asyncio
async def test_assemble_returns_3_tier_sections(super_and_mission, db_session):
    from app.domain.memory.reader import assemble_long_memory_md

    md = await assemble_long_memory_md(
        db_session,
        super_agent_id=super_and_mission["super_id"],
        mission_id=super_and_mission["mission_id"],
    )
    assert "MissionMemory" in md or "§1" in md
    assert "Mission-level" in md  # mission memory content
    assert "SuperMemory" in md or "§2" in md
    assert "超角色长期记忆" in md
    # platform tier 现在为空 → 应输出空占位（不抛错）
    assert "PlatformKB" in md or "§3" in md or "platform" in md.lower()


@pytest.mark.asyncio
async def test_assemble_no_mission_memory_yields_empty_section(super_and_mission, db_session):
    """新 mission 还没 memory → §1 区段输出 empty 标记，不报错。"""
    from app.domain.memory.reader import assemble_long_memory_md
    from app.models.mission import Mission

    fresh_mid = uuid.uuid4()
    db_session.add(Mission(
        id=fresh_mid, name="fresh", slug="fresh",
        supervisor_agent_id=super_and_mission["super_id"],
        created_by=uuid.uuid4(),
    ))
    await db_session.commit()
    md = await assemble_long_memory_md(
        db_session,
        super_agent_id=super_and_mission["super_id"],
        mission_id=fresh_mid,
    )
    assert "empty" in md.lower() or "无" in md
    # super memory 还在
    assert "超角色长期记忆" in md


@pytest.mark.asyncio
async def test_assemble_robust_when_super_id_missing(super_and_mission, db_session):
    from app.domain.memory.reader import assemble_long_memory_md

    md = await assemble_long_memory_md(
        db_session,
        super_agent_id=None,
        mission_id=super_and_mission["mission_id"],
    )
    # mission tier 仍有
    assert "Mission-level" in md
    # super tier 应输出 empty
    assert ("empty" in md.lower()) or ("无" in md)
