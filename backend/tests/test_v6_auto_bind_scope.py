"""R2-4 · auto_bind 走 declarative Skill.scope（不再依赖 DEFAULT_AUTO_BIND_SKILL_EXCLUDE 黑名单）。

锁定 invariant（黑名单删之后必须仍然成立）：
- 建 kind='worker' agent 时，scope='super' 的 skill 不应被自动绑
- 建 kind='super' agent 时，scope='super' / 'all' 的 skill 应被自动绑
- 建 kind='worker' 时，scope='worker' / 'all' 的 skill 应被自动绑
- 建 kind='super' 时，scope='worker' 的 skill 不应被自动绑
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
async def seeded_skills(db_session):
    """种 4 个 builtin skill 各 scope，加 1 个 provider/model 给 agent 绑。"""
    from app.models.skill import Skill
    from app.models.provider import LLMProvider, LLMModel

    # provider + model
    pid = uuid.uuid4()
    db_session.add(LLMProvider(
        id=pid, name="testp", provider_type="custom",
        api_key="x", base_url="https://example.com",
    ))
    mid = uuid.uuid4()
    db_session.add(LLMModel(
        id=mid, provider_id=pid, model_id="testmodel",
        display_name="testmodel", model_type="chat",
    ))

    # 4 skills with explicit scope
    db_session.add_all([
        Skill(id=uuid.uuid4(), name="invoke_worker", slug="invoke_worker",
              skill_type="tool_builtin", builtin_ref="invoke_worker",
              is_builtin=True, category="custom", scope="super", intent="dispatch"),
        Skill(id=uuid.uuid4(), name="return_result", slug="return_result",
              skill_type="tool_builtin", builtin_ref="return_result",
              is_builtin=True, category="custom", scope="worker", intent="io"),
        Skill(id=uuid.uuid4(), name="knowledge_search", slug="knowledge_search",
              skill_type="tool_builtin", builtin_ref="knowledge_search",
              is_builtin=True, category="custom", scope="all", intent="knowledge"),
        Skill(id=uuid.uuid4(), name="builder_only", slug="builder_only_x",
              skill_type="tool_builtin", builtin_ref="builder_only_x",
              is_builtin=True, category="builder", scope="builder", intent="dispatch"),
    ])
    await db_session.commit()
    return {"model_id": mid}


def _bound_slugs(agent) -> set[str]:
    return {b.skill.slug for b in (agent.skills or []) if b.skill is not None}


@pytest.mark.asyncio
async def test_worker_does_not_get_super_only_skill(seeded_skills, db_session):
    """RED → GREEN tracer: worker 不应自动绑 scope='super' 的 invoke_worker。"""
    from app.services.agent_service import create_agent
    from app.schemas.agent import AgentCreate

    payload = AgentCreate(
        name="w1", category="custom", kind="worker",
        model_id=seeded_skills["model_id"],
        soul_md="", protocol_md="",
    )
    agent = await create_agent(db_session, payload)
    bound = _bound_slugs(agent)
    assert "invoke_worker" not in bound, f"worker 不应有 super-only skill, got {bound}"
    # 但应有 worker / all scope 的
    assert "return_result" in bound
    assert "knowledge_search" in bound


@pytest.mark.asyncio
async def test_super_gets_super_and_all_skills(seeded_skills, db_session):
    from app.services.agent_service import create_agent
    from app.schemas.agent import AgentCreate

    payload = AgentCreate(
        name="s1", category="custom", kind="super",
        model_id=seeded_skills["model_id"],
        soul_md="", protocol_md="",
    )
    agent = await create_agent(db_session, payload)
    bound = _bound_slugs(agent)
    assert "invoke_worker" in bound, f"super 应有 super-only skill, got {bound}"
    assert "knowledge_search" in bound  # scope='all'
    # 但不该有 worker-only
    assert "return_result" not in bound, "super 不该有 worker-only skill"


@pytest.mark.asyncio
async def test_super_does_not_get_builder_only_skills(seeded_skills, db_session):
    """builder category skill 仍走 DEFAULT_AUTO_BIND_CATEGORY_EXCLUDE 防御。"""
    from app.services.agent_service import create_agent
    from app.schemas.agent import AgentCreate

    payload = AgentCreate(
        name="s2", category="custom", kind="super",
        model_id=seeded_skills["model_id"],
        soul_md="", protocol_md="",
    )
    agent = await create_agent(db_session, payload)
    bound = _bound_slugs(agent)
    assert "builder_only_x" not in bound


@pytest.mark.asyncio
async def test_default_auto_bind_skill_exclude_is_gone():
    """contract: 这个 constant 应该被删（或至少缩到 0）。"""
    from app.services import agent_service
    legacy = getattr(agent_service, "DEFAULT_AUTO_BIND_SKILL_EXCLUDE", None)
    assert legacy is None or len(legacy) == 0, (
        f"DEFAULT_AUTO_BIND_SKILL_EXCLUDE 应被删 (R2-4 contract); 当前 = {legacy}"
    )
