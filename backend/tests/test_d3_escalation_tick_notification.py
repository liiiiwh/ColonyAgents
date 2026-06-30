"""ADR-028 D3 (2) · escalation 投递时把「你有 N 条未处理升级」enqueue 进 builder super_inbox。

daemon tick 不加载主线程历史 → 必须主动喂进 tick 上下文（pending queue），
让 auto-drain 能感知到升级。断言 enqueue_user_message 被调用，且 meta 带
source='escalation_notification' + escalation_id + unresolved_count。

注：super_pending_messages 表是 raw-DDL（无 ORM 模型，sqlite 测试库不建），且
enqueue 用 PG `CAST(... AS jsonb)` —— 真实落库走 PG。这里 mock 掉 enqueue 验证调用契约。
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models.agent import Agent
from app.models.mission import Mission, MissionEscalation
from app.models.message import Message
from app.models.user import User
from app.services import escalation_dispatcher
from app.services.escalation_dispatcher import deliver_escalation


async def _seed(db):
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
        created_by=user.id, workflow_config={}, runtime_status="running",
    )
    db.add(super_mission)
    await db.flush()
    esc = MissionEscalation(
        mission_id=super_mission.id, created_at=datetime.now(UTC), category="structural",
        severity="warn", summary="缺『跨区域调拨审批』能力",
        proposed_change="新建 dispatch_approver worker", fingerprint="fp-d3-notif", status="pending",
    )
    db.add(esc)
    await db.commit()
    return builder_mission, super_mission, esc


@pytest.mark.asyncio
async def test_deliver_enqueues_unresolved_notification(db_session, _patched_session_local, monkeypatch):
    builder_mission, super_mission, esc = await _seed(db_session)

    captured: dict = {}

    async def _fake_enqueue(db, mission_id, super_agent_id, content, *, meta=None, **kw):
        captured["mission_id"] = mission_id
        captured["content"] = content
        captured["meta"] = meta or {}
        return {"ok": True}

    # 强制走「Builder 忙」分支（避免 idle-trigger 起真 tick），并 mock 掉 PG-only enqueue
    monkeypatch.setattr(
        "app.services.super_inbox.is_running", lambda pid: True
    )
    monkeypatch.setattr(
        "app.services.pending_queue.enqueue_user_message", _fake_enqueue
    )

    await deliver_escalation(esc.id)

    assert captured, "应 enqueue 一条升级通知进 builder super_inbox"
    assert captured["mission_id"] == builder_mission.id
    assert captured["meta"].get("source") == "escalation_notification"
    assert captured["meta"].get("escalation_id") == str(esc.id)
    assert captured["meta"].get("unresolved_count") == 1
    assert "#1" in captured["content"]


@pytest.mark.asyncio
async def test_deliver_still_routes_to_builder_main_thread(db_session, _patched_session_local, monkeypatch):
    """D3 (2) 不破坏 D 既有：escalation 仍落 builder 主线程 + 标 delivered。"""
    builder_mission, super_mission, esc = await _seed(db_session)

    async def _fake_enqueue(db, mission_id, super_agent_id, content, *, meta=None, **kw):
        return {"ok": True}

    monkeypatch.setattr("app.services.super_inbox.is_running", lambda pid: True)
    monkeypatch.setattr("app.services.pending_queue.enqueue_user_message", _fake_enqueue)

    await deliver_escalation(esc.id)

    msgs = (await db_session.execute(
        select(Message).where(Message.mission_id == builder_mission.id, Message.thread_key == "main")
    )).scalars().all()
    assert any("[project-escalation from logi-run]" in (m.content or "") for m in msgs)

    await db_session.refresh(esc)
    assert esc.status == "delivered"
