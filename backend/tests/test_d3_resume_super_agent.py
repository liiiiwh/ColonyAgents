"""ADR-028 D3 (3) · 升级闭环收口：Builder 处理完 → resume_super_agent 唤醒被卡 super。

被卡 super 处于 paused_waiting_capability（request_new_capability 落的态）。
Builder 建好缺失 worker 后调 resume_super_agent：
- super mission lifecycle_status: paused_waiting_capability → running
- 对应 pending/delivered 的 structural/worker_health escalation 被闭环为 acted
- 立即触发一次 super tick（mock 掉避免跑真 LLM）

每个行为一测。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models.agent import Agent
from app.models.mission import Mission, MissionEscalation
from app.models.user import User
from app.skills_builtin.builder.builder_lifecycle_skills import resume_super_agent_tool
from app.skills_builtin.context import BuiltinToolContext


async def _seed_blocked_super(db):
    """建 builder_mission 产出的 super，其 mission 因缺能力 paused_waiting_capability。

    返回 (builder_mission, super_mission, super_agent, esc)。
    """
    user = User(username="u", email="u@x.com", hashed_password="x", role="admin")
    builder_agent = Agent(name="Builder", category="builder", kind="super", slug="builder")
    db.add_all([user, builder_agent])
    await db.flush()
    builder_mission = Mission(
        name="设计会话", slug="builder-mission", supervisor_agent_id=builder_agent.id,
        created_by=user.id, workflow_config={},
    )
    db.add(builder_mission)
    await db.flush()
    super_agent = Agent(
        name="logi-super", kind="super", category="custom", slug="logi",
        built_by_mission_id=builder_mission.id,
    )
    db.add(super_agent)
    await db.flush()
    super_mission = Mission(
        name="物流运行", slug="logi-run", supervisor_agent_id=super_agent.id,
        created_by=user.id, workflow_config={},
        lifecycle_status="paused_waiting_capability", runtime_status="stopped",
        paused_reason="缺 dispatch_approver",
    )
    db.add(super_mission)
    await db.flush()
    esc = MissionEscalation(
        mission_id=super_mission.id, created_at=datetime.now(UTC), category="structural",
        severity="warn", summary="缺『跨区域调拨审批』能力",
        proposed_change="新建 dispatch_approver worker", fingerprint="fp-d3-resume", status="delivered",
    )
    db.add(esc)
    await db.commit()
    return builder_mission, super_mission, super_agent, esc


@pytest.fixture
def _stub_run_once(monkeypatch):
    """mock mission_daemon.run_once，避免触发真 LLM tick；记录被调 mission_id。"""
    calls: list = []

    async def _fake_run_once(db, mission_id, payload=None):
        calls.append(mission_id)
        return {"ok": True}

    monkeypatch.setattr("app.services.mission_daemon.run_once", _fake_run_once)
    return calls


@pytest.mark.asyncio
async def test_resume_transitions_waiting_capability_to_running(
    db_session, _patched_session_local, _stub_run_once
):
    """核心行为：paused_waiting_capability → running（D3 闭环收口）。"""
    builder_mission, super_mission, super_agent, esc = await _seed_blocked_super(db_session)

    ctx = BuiltinToolContext(mission_id=builder_mission.id, db_factory=_patched_session_local)
    tool = resume_super_agent_tool(ctx)
    out = json.loads(await tool.coroutine(super_agent_id=str(super_agent.id)))

    assert out["ok"] is True
    assert out["previous_status"] == "paused_waiting_capability"

    await db_session.refresh(super_mission)
    assert super_mission.lifecycle_status == "running", "被卡 super 应被唤醒回 running"


@pytest.mark.asyncio
async def test_resume_closes_pending_escalation(
    db_session, _patched_session_local, _stub_run_once
):
    """structural escalation 被闭环为 acted。"""
    builder_mission, super_mission, super_agent, esc = await _seed_blocked_super(db_session)

    ctx = BuiltinToolContext(mission_id=builder_mission.id, db_factory=_patched_session_local)
    tool = resume_super_agent_tool(ctx)
    await tool.coroutine(super_agent_id=str(super_agent.id), notes="建好 dispatch_approver")

    await db_session.refresh(esc)
    assert esc.status == "acted", "缺能力 escalation 应被 resume 闭环"


@pytest.mark.asyncio
async def test_resume_triggers_super_tick(
    db_session, _patched_session_local, _stub_run_once
):
    """resume 后立即触发一次 super tick。"""
    builder_mission, super_mission, super_agent, esc = await _seed_blocked_super(db_session)

    ctx = BuiltinToolContext(mission_id=builder_mission.id, db_factory=_patched_session_local)
    tool = resume_super_agent_tool(ctx)
    await tool.coroutine(super_agent_id=str(super_agent.id))

    assert _stub_run_once == [super_mission.id], "应对被唤醒的 super mission 起一轮 tick"


@pytest.mark.asyncio
async def test_resume_unknown_super_returns_error(
    db_session, _patched_session_local, _stub_run_once
):
    """找不到 super_agent 关联的 mission → 友好报错，不抛。"""
    import uuid as _uuid
    ctx = BuiltinToolContext(mission_id=None, db_factory=_patched_session_local)
    tool = resume_super_agent_tool(ctx)
    out = json.loads(await tool.coroutine(super_agent_id=str(_uuid.uuid4())))
    assert out["ok"] is False
    assert _stub_run_once == [], "未找到 mission 不应触发 tick"
