"""ADR-028 D4 · scheduler fire_one 按 mission lifecycle 决定 run/skip。

- paused_for_human / stopped / error → SKIP（观感=停调度），但不动 schedule.enabled。
- paused_idle / running → RUN（到点拉新一轮）。
"""
from __future__ import annotations

import uuid

import pytest

from app.models.agent import Agent
from app.models.mission import Mission, MissionSchedule
from app.models.user import User
from app.services import scheduler_service

pytestmark = pytest.mark.asyncio


async def _mk_mission_with_schedule(db, lifecycle: str) -> MissionSchedule:
    u = User(username=f"u-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@t.io",
             hashed_password="x")
    db.add(u)
    await db.flush()
    ag = Agent(name=f"sup-{uuid.uuid4().hex[:6]}", category="custom", kind="super",
               model_id=None, soul_md="x", protocol_md="x")
    db.add(ag)
    await db.flush()
    proj = Mission(name="m", slug=f"m-{uuid.uuid4().hex[:8]}",
                   supervisor_agent_id=ag.id, created_by=u.id,
                   lifecycle_status=lifecycle, runtime_status="running")
    db.add(proj)
    await db.flush()
    sched = MissionSchedule(mission_id=proj.id, name="cron", kind="cron",
                            expr="* * * * *", enabled=True, created_by=u.id)
    db.add(sched)
    await db.commit()
    await db.refresh(sched)
    return sched


@pytest.mark.parametrize("lifecycle", [
    "paused_clarification", "paused_waiting_capability", "stopped", "error",
])
async def test_fire_one_skips_paused_or_stopped(
    db_session, _patched_session_local, monkeypatch, lifecycle
):
    sched = await _mk_mission_with_schedule(db_session, lifecycle)

    called = {"n": 0}

    async def _fake_run_once(db, mid, payload):
        called["n"] += 1
        return {"ok": True}

    from app.services import mission_daemon
    monkeypatch.setattr(mission_daemon, "run_once", _fake_run_once)

    res = await scheduler_service.fire_one(sched.id)
    assert called["n"] == 0, "人工门/停止态不应触发 run_once"
    assert res.get("skipped") == "lifecycle_gate"

    # schedule.enabled 永不被代码改（H4）—— 在独立 session 验证，避免 sqlite in-memory 锁竞争
    async with _patched_session_local() as vdb:
        fresh = await vdb.get(MissionSchedule, sched.id)
        assert fresh.enabled is True


@pytest.mark.parametrize("lifecycle", ["running", "paused_idle"])
async def test_fire_one_runs_for_running_or_paused_idle(
    db_session, _patched_session_local, monkeypatch, lifecycle
):
    sched = await _mk_mission_with_schedule(db_session, lifecycle)

    called = {"n": 0}

    async def _fake_run_once(db, mid, payload):
        called["n"] += 1
        return {"ok": True}

    from app.services import mission_daemon
    monkeypatch.setattr(mission_daemon, "run_once", _fake_run_once)

    await scheduler_service.fire_one(sched.id)
    assert called["n"] == 1, "running / paused_idle 应触发 run_once"
