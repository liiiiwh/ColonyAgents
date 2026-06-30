"""ADR-009 G1 · 跨 super 消费查询 + 影响分析联动（集成）。

apply_worker_spec 的端到端 happy-path 在 sqlite 上要 eager-load 一堆关系表（mcp/aux 等），
不适合做轻量集成测；故在 G1 真正新增的 DB 接缝 `find_supers_using_capability` 上测，
配合 analyze_worker_change_impact（纯，已单测）证明硬阻断判定成立。工厂里的 3 行
call+raise 由真实 LLM e2e 覆盖。
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


async def _seed_consumer_super(db, *, slug, capabilities):
    from app.models.agent import Agent
    from app.models.mission import Mission
    sup = Agent(
        name=slug, description="", category="custom", kind="super",
        model_id=uuid.uuid4(), extra_config={"required_capabilities": capabilities},
    )
    db.add(sup)
    await db.flush()
    db.add(Mission(name=slug, slug=slug, supervisor_agent_id=sup.id, created_by=uuid.uuid4()))
    await db.commit()


@pytest.mark.asyncio
async def test_consumer_query_finds_declared_super(spec_db):
    from app.domain.builder.capability_consumers import find_supers_using_capability
    old = {"advertises": [{"action": "publish_note"}, {"action": "comment"}]}
    async with spec_db() as db:
        await _seed_consumer_super(db, slug="xhs-a", capabilities=["xhs_ops"])
        await _seed_consumer_super(db, slug="other", capabilities=["zhihu_ops"])  # 不相关
        cons = await find_supers_using_capability(db, "xhs_ops", old_contract=old)
    assert len(cons) == 1
    assert cons[0]["super_slug"] == "xhs-a"
    # 声明-only 保守按用了全部旧 action
    assert set(cons[0]["used_actions"]) == {"publish_note", "comment"}
    assert cons[0]["source"] == "declared"


@pytest.mark.asyncio
async def test_consumer_query_plus_impact_blocks_breaking_change(spec_db):
    from app.domain.builder.capability_consumers import find_supers_using_capability
    from app.domain.builder.spec_validation import analyze_worker_change_impact
    old = {"advertises": [{"action": "publish_note"}, {"action": "comment"}]}
    new = {"advertises": [{"action": "publish_note"}], "deprecated_actions": ["comment"]}
    async with spec_db() as db:
        await _seed_consumer_super(db, slug="xhs-a", capabilities=["xhs_ops"])
        cons = await find_supers_using_capability(db, "xhs_ops", old_contract=old)
    impact = analyze_worker_change_impact(old_contract=old, new_contract=new, consumers=cons)
    assert impact["safe"] is False
    assert impact["breaking"][0]["super_slug"] == "xhs-a"
    assert "comment" in impact["breaking"][0]["broken_actions"]


@pytest.mark.asyncio
async def test_consumer_query_plus_impact_allows_compatible_change(spec_db):
    from app.domain.builder.capability_consumers import find_supers_using_capability
    from app.domain.builder.spec_validation import analyze_worker_change_impact
    old = {"advertises": [{"action": "publish_note"}, {"action": "comment"}]}
    new = {"advertises": [{"action": "publish_note"}, {"action": "comment"}, {"action": "repost"}]}
    async with spec_db() as db:
        await _seed_consumer_super(db, slug="xhs-a", capabilities=["xhs_ops"])
        cons = await find_supers_using_capability(db, "xhs_ops", old_contract=old)
    impact = analyze_worker_change_impact(old_contract=old, new_contract=new, consumers=cons)
    assert impact["safe"] is True


@pytest.mark.asyncio
async def test_govern_rejects_malformed_contract(spec_db):
    from app.domain.builder.capability_consumers import govern_worker_contract_change
    async with spec_db() as db:
        with pytest.raises(ValueError, match="不合规"):
            await govern_worker_contract_change(
                db, capability="x", slug="x",
                old_contract=None,
                new_contract={"advertises": [{"action": "a"}]},  # 缺 side_effects/requires_approval
            )


@pytest.mark.asyncio
async def test_govern_allows_new_worker_with_valid_contract(spec_db):
    from app.domain.builder.capability_consumers import govern_worker_contract_change
    async with spec_db() as db:
        # old=None（新建）+ 结构合法 → 放行（无异常）
        await govern_worker_contract_change(
            db, capability="x", slug="x", old_contract=None,
            new_contract={"advertises": [{"action": "a", "side_effects": [], "requires_approval": False}]},
        )


@pytest.mark.asyncio
async def test_govern_blocks_breaking_upgrade_for_consumer(spec_db):
    from app.domain.builder.capability_consumers import govern_worker_contract_change
    old = {"advertises": [
        {"action": "publish", "side_effects": [], "requires_approval": False},
        {"action": "comment", "side_effects": [], "requires_approval": False},
    ]}
    new = {"advertises": [
        {"action": "publish", "side_effects": [], "requires_approval": False},
    ], "deprecated_actions": ["comment"]}
    async with spec_db() as db:
        await _seed_consumer_super(db, slug="xhs-a", capabilities=["xhs_ops"])
        with pytest.raises(ValueError, match="一边好一边坏|破坏"):
            await govern_worker_contract_change(
                db, capability="xhs_ops", slug="xhs_ops", old_contract=old, new_contract=new,
            )


@pytest.mark.asyncio
async def test_no_consumers_when_capability_unused(spec_db):
    from app.domain.builder.capability_consumers import find_supers_using_capability
    async with spec_db() as db:
        await _seed_consumer_super(db, slug="other", capabilities=["zhihu_ops"])
        cons = await find_supers_using_capability(db, "xhs_ops", old_contract={"advertises": []})
    assert cons == []
