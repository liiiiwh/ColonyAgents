"""ADR-018 D2 · Colony Worker Optimization singleton system super.

The platform's single non-deletable super that owns the worker iteration loop. These tests pin
the structural singleton (idempotent seed + system invariants); the routing/tick wiring is
covered where those behaviors live.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.user import User
from app.services.worker_optimization_service import (
    WORKER_OPT_AGENT_NAME,
    WORKER_OPT_SLUG,
    ensure_worker_optimization_super,
)

pytestmark = pytest.mark.asyncio


async def _seed_admin(db) -> None:
    db.add(User(username="admin", email="admin@t.io", hashed_password="x"))
    await db.commit()


async def test_seeds_singleton_system_super_and_mission(db_session):
    await _seed_admin(db_session)
    agent, mission = await ensure_worker_optimization_super(db_session)

    assert agent.name == WORKER_OPT_AGENT_NAME
    assert agent.kind == "super"
    assert agent.is_system is True
    assert agent.model_id is None  # resolves platform default at runtime (ADR-017)

    assert mission.slug == WORKER_OPT_SLUG
    assert mission.is_system is True
    assert mission.supervisor_agent_id == agent.id


async def test_seed_is_idempotent(db_session):
    await _seed_admin(db_session)
    a1, m1 = await ensure_worker_optimization_super(db_session)
    a2, m2 = await ensure_worker_optimization_super(db_session)
    assert a1.id == a2.id  # one super, not duplicated
    assert m1.id == m2.id  # one fixed mission, not duplicated


async def test_returns_none_without_admin(db_session):
    # Seeded before any admin exists → no mission can be created yet.
    res = await ensure_worker_optimization_super(db_session)
    assert res is None


async def test_submit_worker_issue_spawns_work_order(db_session, _patched_session_local):
    # ADR-025 · a super's worker report spawns a dedicated work-order mission (not the singleton),
    # with the report persisted in ITS main thread regardless of the kickoff tick outcome.
    from sqlalchemy import select

    from app.models.message import Message
    from app.models.mission import Mission
    from app.services.worker_health_service import submit_worker_issue

    await _seed_admin(db_session)
    agent, dispatcher = await ensure_worker_optimization_super(db_session)

    await submit_worker_issue(
        db_session, capability="xhs_ops", evidence="3/5 calls failed: rate-limit", severity="warn",
    )

    # 一个独立 work-order mission（slug wo-xhs_ops-*），不是单例 dispatcher
    wo = (await db_session.execute(
        select(Mission).where(
            Mission.supervisor_agent_id == agent.id,
            Mission.slug.like("wo-xhs_ops-%"),
        )
    )).scalars().first()
    assert wo is not None
    assert wo.id != dispatcher.id

    rows = (await db_session.execute(
        select(Message).where(Message.mission_id == wo.id, Message.thread_key == "main")
    )).scalars().all()
    reports = [m for m in rows if (m.meta or {}).get("type") == "worker_issue_report"]
    assert len(reports) == 1
    assert reports[0].meta["capability"] == "xhs_ops"


async def test_submit_worker_issue_false_when_super_absent(db_session):
    # No worker-opt super seeded (no admin) → nothing delivered.
    from app.services.worker_health_service import submit_worker_issue

    ok = await submit_worker_issue(db_session, capability="x", evidence="y")
    assert ok is False
