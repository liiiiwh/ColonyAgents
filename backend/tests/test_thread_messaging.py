"""ADR-018/020 mission-only · 按 (mission_id, thread_key) 的写/读/广播。

thread 身份 = 一个 thread_key 字符串（main / worker:{super_id}:{worker_id} / health），
没有 session/session_branch 行，也没有 thread_key_for 纯函数（已内联/删除，ADR-020）。
"""
from __future__ import annotations

import uuid

import pytest

from app.models.mission import Mission

pytestmark = pytest.mark.asyncio


async def _mk_mission(db) -> uuid.UUID:
    """建最小 Mission(Mission)，返回 mission_id。"""
    from app.models.agent import Agent
    from app.models.user import User

    u = User(username=f"u-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@t.io", hashed_password="x")
    db.add(u)
    await db.flush()
    ag = Agent(name=f"sup-{uuid.uuid4().hex[:6]}", category="custom", kind="super",
               model_id=None, soul_md="x", protocol_md="x")
    db.add(ag)
    await db.flush()
    proj = Mission(name="t", slug=f"p-{uuid.uuid4().hex[:8]}", supervisor_agent_id=ag.id, created_by=u.id)
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj.id


# ── append_message / list_thread_messages 按 (mission_id, thread_key) ──

async def test_append_message_stamps_mission_and_thread_key(db_session):
    from app.services.messaging_service import append_message

    mid = await _mk_mission(db_session)
    wtk = f"worker:{uuid.uuid4()}:{uuid.uuid4()}"
    msg = await append_message(db_session, mid, wtk, "user", "hi", publish=False)
    assert msg.thread_key == wtk
    assert msg.mission_id == mid

    m2 = await append_message(db_session, mid, "main", "assistant", "ok", publish=False)
    assert m2.thread_key == "main"


async def test_list_thread_messages_by_mission_and_thread(db_session):
    from app.services.messaging_service import append_message, list_thread_messages

    mid = await _mk_mission(db_session)
    wtk = f"worker:{uuid.uuid4()}:{uuid.uuid4()}"
    await append_message(db_session, mid, "main", "user", "hello main", publish=False)
    await append_message(db_session, mid, wtk, "user", "hello worker", publish=False)
    await append_message(db_session, mid, "main", "assistant", "reply main", publish=False)

    main_msgs = await list_thread_messages(db_session, mid, "main")
    assert [m.content for m in main_msgs] == ["hello main", "reply main"]  # ordered, thread-scoped

    wk_msgs = await list_thread_messages(db_session, mid, wtk)
    assert [m.content for m in wk_msgs] == ["hello worker"]


async def test_append_message_publishes_on_mission_channel(db_session):
    # event_bus channel = Mission (mission_id)：一个 mission 的所有 thread 共用一个频道。
    import asyncio
    import app.services.event_bus as eb
    from app.services.messaging_service import append_message

    eb.reset_for_test()
    mid = await _mk_mission(db_session)

    got: list = []

    async def _consume():
        async for evt in eb.bus.subscribe(mid):  # subscribe on the MISSION channel
            got.append(evt)
            break

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.05)  # let the subscriber register its queue before we publish
    await append_message(db_session, mid, "main", "assistant", "hi mission", publish=True)
    await asyncio.wait_for(task, timeout=1.0)

    assert got and got[0]["type"] == "message"
    assert got[0]["content"] == "hi mission"
