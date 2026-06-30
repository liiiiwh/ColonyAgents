"""ADR-028 D4 · Mission 生命周期门控（daemon 侧）。

- _should_skip_tick：paused_for_human（clarification/waiting_capability）→ skip；
  stopped → skip；paused_idle → 放行（它是调度拉起的恢复点）。
- run_once 收尾：tick 正常结束、无 force_human 门、无外部 pending → 转 paused_idle。
"""
from __future__ import annotations

import uuid

import pytest

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.services import mission_daemon as md

pytestmark = pytest.mark.asyncio


async def _mk_mission(db, lifecycle: str) -> Mission:
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
    await db.commit()
    await db.refresh(proj)
    return proj


async def test_skip_tick_paused_for_human(db_session):
    """paused_clarification / paused_waiting_capability → skip。"""
    for ls in ("paused_clarification", "paused_waiting_capability"):
        proj = await _mk_mission(db_session, ls)
        reason, _d = await md._should_skip_tick(db_session, proj.id, proj, {"trigger": "cron"})
        assert reason == ls


async def test_skip_tick_stopped(db_session):
    """ADR-028 D4：stopped → skip（新增第四块）。"""
    proj = await _mk_mission(db_session, "stopped")
    reason, _d = await md._should_skip_tick(db_session, proj.id, proj, {"trigger": "cron"})
    assert reason == "stopped"


async def test_paused_idle_is_let_through(db_session):
    """ADR-028 D4：paused_idle 不被 skip（调度拉起的恢复点，放行）。"""
    proj = await _mk_mission(db_session, "paused_idle")
    reason, _d = await md._should_skip_tick(db_session, proj.id, proj, {"trigger": "cron 0 * * * *"})
    assert reason is None
