"""ADR-025 D1 · Work-Order Mission：每个退化 worker 一个 ephemeral mission。

- spawn：退化 worker → 新建独立 work-order mission（supervisor=worker-opt super，报告进 main）
- attach：同 worker(capability) 已有未归档 work-order → 复用不新建（同 worker 串行去重）
- 跨 worker 并行：不同 capability → 各自独立 mission
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.services.messaging_service import list_thread_messages
from app.services.worker_optimization_service import spawn_or_attach_work_order

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


async def test_spawn_creates_work_order_mission(db_session):
    """退化 worker → 新建 work-order mission，supervisor=worker-opt super，报告进 main 线程。"""
    sup, u = await _mk_optsuper(db_session)
    m, created = await spawn_or_attach_work_order(
        db_session, super_agent_id=sup.id, created_by=u.id,
        capability="data_fetcher", worker_agent_id="w1", report="data_fetcher 反复 500",
    )
    assert created is True
    assert m.supervisor_agent_id == sup.id
    msgs = await list_thread_messages(db_session, m.id, "main")
    assert any("data_fetcher 反复 500" in (mm.content or "") for mm in msgs)


async def test_attach_dedups_same_capability(db_session):
    """同 capability 已有未归档 work-order → 复用同一 mission，报告追加进去。"""
    sup, u = await _mk_optsuper(db_session)
    m1, c1 = await spawn_or_attach_work_order(
        db_session, super_agent_id=sup.id, created_by=u.id,
        capability="data_fetcher", worker_agent_id="w1", report="第一份证据",
    )
    m2, c2 = await spawn_or_attach_work_order(
        db_session, super_agent_id=sup.id, created_by=u.id,
        capability="data_fetcher", worker_agent_id="w1", report="第二份证据",
    )
    assert c1 is True and c2 is False
    assert m2.id == m1.id
    cnt = (await db_session.execute(
        select(func.count()).select_from(Mission).where(
            Mission.supervisor_agent_id == sup.id
        )
    )).scalar()
    assert cnt == 1  # 没新建第二个


async def test_different_capability_separate_missions(db_session):
    """不同 capability → 各自独立 work-order mission（跨 worker 并行）。"""
    sup, u = await _mk_optsuper(db_session)
    m1, _ = await spawn_or_attach_work_order(
        db_session, super_agent_id=sup.id, created_by=u.id,
        capability="data_fetcher", worker_agent_id="w1", report="a",
    )
    m2, _ = await spawn_or_attach_work_order(
        db_session, super_agent_id=sup.id, created_by=u.id,
        capability="report_writer", worker_agent_id="w2", report="b",
    )
    assert m1.id != m2.id
