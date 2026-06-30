"""ADR-025 D1 · 派发器：体检候选 → 每个退化 worker 一个 work-order（dedup 去重）。"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.domain.optimization.health_scan import WorkerHealthCandidate
from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.services.worker_health_service import dispatch_health_candidates

pytestmark = pytest.mark.asyncio


async def _mk_optsuper(db) -> tuple[Agent, User]:
    u = User(username=f"u-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@t.io",
             hashed_password="x")
    db.add(u)
    await db.flush()
    sup = Agent(name=f"opt-{uuid.uuid4().hex[:6]}", category="utility", kind="super",
                model_id=None, soul_md="x", protocol_md="x")
    db.add(sup)
    await db.commit()
    await db.refresh(sup)
    return sup, u


def _cand(cap: str) -> WorkerHealthCandidate:
    return WorkerHealthCandidate(
        worker_id=str(uuid.uuid4()), name=f"W·{cap}", capability=cap,
        success_rate=0.4, total=12, reason="退化", top_error_msg="500",
    )


async def test_dispatch_fans_out_one_mission_per_worker(db_session):
    """两个不同 capability 的退化候选 → 两个独立 work-order mission。"""
    sup, u = await _mk_optsuper(db_session)
    missions = await dispatch_health_candidates(
        db_session, super_agent_id=sup.id, created_by=u.id,
        candidates=[_cand("data_fetcher"), _cand("report_writer")],
    )
    assert len({m.id for m in missions}) == 2


async def test_dispatch_dedups_same_capability(db_session):
    """同 capability 的两个候选 → 复用同一 work-order（同 worker 串行去重）。"""
    sup, u = await _mk_optsuper(db_session)
    await dispatch_health_candidates(
        db_session, super_agent_id=sup.id, created_by=u.id, candidates=[_cand("data_fetcher")],
    )
    await dispatch_health_candidates(
        db_session, super_agent_id=sup.id, created_by=u.id, candidates=[_cand("data_fetcher")],
    )
    cnt = (await db_session.execute(
        select(func.count()).select_from(Mission).where(Mission.supervisor_agent_id == sup.id)
    )).scalar()
    assert cnt == 1
