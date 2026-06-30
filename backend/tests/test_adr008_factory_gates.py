"""ADR-008 P5 · Builder 工厂硬门 fail-fast（集成）。

证明 apply_super_spec / apply_worker_spec 真的会 raise（不只是纯校验器）：
- 缺 skill → ValueError（不静默跳过）
- 畸形 capability_contract → ValueError
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
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
        for tname in (
            "users", "llm_providers", "llm_models",
            "agents", "skills", "agent_skills",
            "missions", "mission_run_state",
        ):
            tbl = Base.metadata.tables.get(tname)
            if tbl is not None:
                try:
                    await conn.run_sync(tbl.create)
                except Exception:
                    pass
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_apply_super_spec_raises_on_missing_skills(spec_db):
    """skills 表为空 → SUPER_REQUIRED_SKILLS 全缺 → 抛错且不留残缺 super。"""
    from app.domain.builder import SuperSpec
    from app.domain.builder.factory import apply_super_spec
    from app.models.agent import Agent
    from sqlalchemy import select

    spec = SuperSpec(
        name="xhs-super", slug="xhs-super", model_id=uuid.uuid4(),
        goal_spec={"description": "运营小红书"}, capabilities=["xhs_ops"],
    )
    async with spec_db() as db:
        with pytest.raises(ValueError, match="skill 未安装"):
            await apply_super_spec(db, spec, created_by=None)
    # 回滚后无残缺 super 落库
    async with spec_db() as db2:
        rows = (await db2.execute(select(Agent).where(Agent.kind == "super"))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_apply_worker_spec_raises_on_malformed_contract(spec_db):
    """capability_contract.advertises 缺 side_effects/requires_approval → 结构校验先于建 agent 抛错。"""
    from app.domain.builder import WorkerSpec
    from app.domain.builder.factory import apply_worker_spec

    spec = WorkerSpec(
        name="bad-worker", slug="bad_worker", model_id=uuid.uuid4(),
        capability="bad_cap",
        capability_contract={
            "capability": "bad_cap", "version": "1.0.0",
            "advertises": [{"action": "do_it"}],  # 缺 side_effects + requires_approval
        },
    )
    async with spec_db() as db:
        with pytest.raises(ValueError, match="capability_contract 不合规"):
            await apply_worker_spec(db, spec, created_by=None)
