"""ADR-028 D4 · H4 调度器原则 · schedule.enabled 永不被代码改。

退役 _maybe_auto_pause_schedules 的有损翻转：unresolved≥3 时不再把 schedule.enabled=False；
调度器控制由 fire_one 按 lifecycle 决定 run/skip（逻辑级门控）。
"""
from __future__ import annotations

import uuid

import pytest

from datetime import UTC, datetime

from app.models.agent import Agent
from app.models.mission import Mission, MissionSchedule, MissionEscalation
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _mk(db) -> tuple[uuid.UUID, uuid.UUID]:
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
                   lifecycle_status="running", runtime_status="running")
    db.add(proj)
    await db.flush()
    sched = MissionSchedule(mission_id=proj.id, name="cron", kind="cron",
                            expr="* * * * *", enabled=True, created_by=u.id)
    db.add(sched)
    # 4 条 unresolved escalation → 超过 AUTO_PAUSE_UNRESOLVED_THRESHOLD
    for i in range(4):
        db.add(MissionEscalation(
            mission_id=proj.id, created_at=datetime.now(UTC),
            category="structural", severity="warn",
            summary=f"x{i}", fingerprint=uuid.uuid4().hex, status="pending",
        ))
    await db.commit()
    return proj.id, sched.id


async def test_auto_pause_no_longer_flips_enabled(db_session):
    pid, sched_id = await _mk(db_session)
    from app.skills_builtin.builder import escalation_skills as es

    triggered = await es._maybe_auto_pause_schedules(db_session, pid)
    assert triggered is False, "H4：不再做有损 enabled 翻转"

    db_session.expire_all()
    sched = await db_session.get(MissionSchedule, sched_id)
    assert sched.enabled is True, "schedule.enabled 永不被代码改"
