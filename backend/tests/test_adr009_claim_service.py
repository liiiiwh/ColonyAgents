"""ADR-009 G4 · builder_claim_service 行锁 roundtrip（集成）。

session A 拿到锁 → session B 被拒 → A 释放 → B 拿到。
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def claim_db():
    from app.db.base import Base
    import app.models.builder_governance  # noqa

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        tbl = Base.metadata.tables.get("builder_work_claims")
        await conn.run_sync(tbl.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_claim_roundtrip(claim_db):
    from app.services import builder_claim_service as svc
    sA, sB = uuid.uuid4(), uuid.uuid4()

    async with claim_db() as db:
        r1 = await svc.acquire_claim(db, target_type="worker", target_id="xhs_ops", session_id=sA)
        assert r1["outcome"] == "grant"

    # 同一目标，session A 再来 → reuse（幂等）
    async with claim_db() as db:
        r2 = await svc.acquire_claim(db, target_type="worker", target_id="xhs_ops", session_id=sA)
        assert r2["outcome"] == "reuse"

    # session B 抢同一目标 → reject
    async with claim_db() as db:
        r3 = await svc.acquire_claim(db, target_type="worker", target_id="xhs_ops", session_id=sB)
        assert r3["outcome"] == "reject"
        assert r3["ok"] is False

    # A 释放
    async with claim_db() as db:
        rel = await svc.release_claim(db, target_type="worker", target_id="xhs_ops", session_id=sA)
        assert rel["released"] is True

    # B 现在能拿到
    async with claim_db() as db:
        r4 = await svc.acquire_claim(db, target_type="worker", target_id="xhs_ops", session_id=sB)
        assert r4["outcome"] == "grant"


@pytest.mark.asyncio
async def test_release_only_by_holder(claim_db):
    from app.services import builder_claim_service as svc
    sA, sB = uuid.uuid4(), uuid.uuid4()
    async with claim_db() as db:
        await svc.acquire_claim(db, target_type="super", target_id="xhs-colony", session_id=sA)
    async with claim_db() as db:
        # B 不能释放 A 的锁
        rel = await svc.release_claim(db, target_type="super", target_id="xhs-colony", session_id=sB)
        assert rel["released"] is False
    async with claim_db() as db:
        # A 仍持有 → B 申请被拒
        r = await svc.acquire_claim(db, target_type="super", target_id="xhs-colony", session_id=sB)
        assert r["outcome"] == "reject"
