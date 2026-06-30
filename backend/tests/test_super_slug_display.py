"""Super 身份字段：apply_super_spec 给 super agent 落 slug + display_name（URL 与标题用），
不再借用 agent.name。这样 /mission/<super>/<mission> 与「Super · <display_name>」有干净来源。
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def spec_db():
    from app.db.base import Base
    import app.models.user  # noqa
    import app.models.provider  # noqa
    import app.models.agent  # noqa
    import app.models.skill  # noqa
    import app.models.mission  # noqa
    import app.models.knowledge  # noqa

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_super_skills(db):
    from app.domain.builder.factory import SUPER_REQUIRED_SKILLS
    from app.models.skill import Skill
    for slug in SUPER_REQUIRED_SKILLS:
        db.add(Skill(slug=slug, name=slug, description="x", skill_type="builtin",
                     builtin_ref=slug, is_enabled=True, is_builtin=True))
    await db.commit()


@pytest.mark.asyncio
async def test_apply_super_spec_sets_slug_and_display_name(spec_db):
    from app.domain.builder import SuperSpec
    from app.domain.builder.factory import apply_super_spec
    from app.models.agent import Agent

    from app.models.provider import LLMModel, LLMProvider
    from app.models.user import User

    async with spec_db() as db:
        await _seed_super_skills(db)
        user = User(username="u", email="u@x.com", hashed_password="x", role="admin")
        db.add(user)
        prov = LLMProvider(name="p", provider_type="openai", api_key="enc")
        db.add(prov)
        await db.flush()
        model = LLMModel(provider_id=prov.id, model_id="m1", display_name="M1")
        db.add(model)
        await db.commit()
        spec = SuperSpec(
            name="服务器运维监控", slug="server-monitor", model_id=model.id,
            goal_spec={"description": "巡检"}, capabilities=["server_ops"],
        )
        ref = await apply_super_spec(db, spec, created_by=user.id)
        agent = await db.get(Agent, ref.agent_id)
        assert agent.slug == "server-monitor"
        assert agent.display_name == "服务器运维监控"
