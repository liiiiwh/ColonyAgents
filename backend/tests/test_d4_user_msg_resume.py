"""ADR-028 D4 · H3 · 用户消息对 paused_* mission 先 RESUME→running 再触发。

给一个 paused_clarification / paused_waiting_capability / paused_idle 的 mission 发消息，
_autostart_and_trigger 应把它恢复到 running（让随后的 tick 不被守卫挡掉）。
"""
from __future__ import annotations

import uuid

import pytest

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _mk_mission(db, lifecycle: str) -> tuple[uuid.UUID, uuid.UUID]:
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
                   lifecycle_status=lifecycle, runtime_status="running",
                   paused_reason="x")
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj.id, u.id


@pytest.mark.parametrize("lifecycle", [
    "paused_clarification", "paused_waiting_capability",
])
async def test_user_msg_resumes_paused_for_human(
    db_session, _patched_session_local, monkeypatch, lifecycle
):
    mid, uid = await _mk_mission(db_session, lifecycle)

    # 不真跑后台 tick
    import app.api.super_conversation as sc

    async def _noop_trigger(mission_id, actor_user_id=None):
        return None

    monkeypatch.setattr(sc, "_trigger_tick_async", _noop_trigger)

    _started, _triggered, _warn, lifecycle_after = await sc._autostart_and_trigger(
        db_session, mid, uid, auto_trigger=True, auto_start=True,
    )

    db_session.expire_all()
    proj = await db_session.get(Mission, mid)
    assert proj.lifecycle_status == "running", "paused_for_human 应先 resume 到 running"
    assert proj.paused_reason is None
    assert lifecycle_after == "running"


async def test_user_msg_keeps_paused_idle_runnable(
    db_session, _patched_session_local, monkeypatch
):
    """paused_idle 也应 resume 到 running（用户消息=立即触发新一轮）。"""
    mid, uid = await _mk_mission(db_session, "paused_idle")

    import app.api.super_conversation as sc

    async def _noop_trigger(mission_id, actor_user_id=None):
        return None

    monkeypatch.setattr(sc, "_trigger_tick_async", _noop_trigger)

    await sc._autostart_and_trigger(
        db_session, mid, uid, auto_trigger=True, auto_start=True,
    )
    db_session.expire_all()
    proj = await db_session.get(Mission, mid)
    assert proj.lifecycle_status == "running"
