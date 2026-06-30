"""新建 Mission 的「它要做什么」(goal_hint) 处理。

POST /api/missions 带 goal_hint：
  - 填了 → 把 goal_hint 当作用户在主 thread 的第一句话（role='user'）写入，并尝试触发 super。
  - 没填 → 主动发一条固定问候语（role='assistant'，内容=system_setting
    `mission.empty_goal_prompt`），且不写任何 user 消息、不触发 super。

mock 掉真实 daemon / pending 队列副作用（super_pending_messages 表在 SQLite 测试库不存在，
daemon.start / _trigger_tick_async 不在单测里跑真实 tick），只断言主 thread 落的消息。
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import system_settings as _ss

pytestmark = pytest.mark.asyncio


async def _auth(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def super_agent_id(seeded_db: AsyncSession) -> uuid.UUID:
    """在共享 session 里建一个 kind='super' agent 供 spawn_mission 用。"""
    from app.models.agent import Agent

    sid = uuid.uuid4()
    seeded_db.add(Agent(
        id=sid, name=f"sup_{sid.hex[:6]}", slug=f"sup-{sid.hex[:6]}",
        display_name="Probe Super", kind="super", category="custom",
        model_id=uuid.uuid4(), soul_md="", protocol_md="",
    ))
    await seeded_db.commit()
    return sid


@pytest.fixture(autouse=True)
def _mute_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    """避免单测里真跑 daemon / 写 super_pending_messages（SQLite 测试库无此表）/ 起异步 tick。"""
    import app.api.super_conversation as sc
    from app.services import mission_daemon

    async def _noop_start(db, mission_id, *, kickoff: bool = False):
        return "running"

    async def _noop_enqueue(db, mission_id, agent_id, content, *, meta=None,
                            max_pending=20, max_content_kb=50):
        return {"ok": True, "message_id": str(uuid.uuid4()), "queue_size_after": 1}

    async def _noop_trigger(mission_id, actor_user_id=None):
        return None

    monkeypatch.setattr(mission_daemon, "start", _noop_start)
    monkeypatch.setattr(sc.super_inbox, "enqueue_user_message", _noop_enqueue)
    monkeypatch.setattr(sc, "_trigger_tick_async", _noop_trigger)


async def _main_messages(db: AsyncSession, mission_id: uuid.UUID):
    from app.models.message import Message

    rows = (await db.execute(
        select(Message)
        .where(Message.mission_id == mission_id, Message.thread_key == "main")
        .order_by(Message.created_at.asc())
    )).scalars().all()
    return rows


async def _create_mission(client: AsyncClient, auth, super_id, *, goal_hint):
    body = {"super_agent_id": str(super_id), "name": "目标测试 Mission"}
    if goal_hint is not None:
        body["goal_hint"] = goal_hint
    resp = await client.post("/api/missions", headers=auth, json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True, data
    return uuid.UUID(data["mission"]["id"])


async def test_goal_hint_filled_posts_user_first_message(
    seeded_client: AsyncClient, seeded_db: AsyncSession, super_agent_id
):
    """填了 goal_hint → 主 thread 落一条 role='user' 消息，内容=goal_hint（strip 后）。"""
    auth = await _auth(seeded_client)
    goal = "  每天早上整理昨天的行业新闻发我  "
    mid = await _create_mission(seeded_client, auth, super_agent_id, goal_hint=goal)

    msgs = await _main_messages(seeded_db, mid)
    user_msgs = [m for m in msgs if m.role == "user"]
    assert len(user_msgs) == 1, [(m.role, m.content) for m in msgs]
    assert user_msgs[0].content == goal.strip()
    # 该消息必须带「真人输入」身份标识（meta.source=='user_chat'），前端 systemUserKind
    # 据此渲染成蓝色用户气泡，而非 🤖 系统·自动。
    assert user_msgs[0].meta.get("source") == "user_chat", user_msgs[0].meta
    # 没填空问候那条 assistant 消息
    assert not [m for m in msgs if m.role == "assistant"]


async def test_goal_hint_empty_posts_fixed_greeting(
    seeded_client: AsyncClient, seeded_db: AsyncSession, super_agent_id
):
    """没填 goal_hint → 主 thread 落一条 role='assistant' 问候语（=system_setting 值），无 user 消息。"""
    auth = await _auth(seeded_client)
    mid = await _create_mission(seeded_client, auth, super_agent_id, goal_hint=None)

    expected = await _ss.get(
        seeded_db,
        _ss.MISSION_EMPTY_GOAL_PROMPT_KEY,
        _ss.MISSION_EMPTY_GOAL_PROMPT_DEFAULT,
    )
    msgs = await _main_messages(seeded_db, mid)
    assert len(msgs) == 1, [(m.role, m.content) for m in msgs]
    assert msgs[0].role == "assistant"
    assert msgs[0].content == expected
    assert msgs[0].meta.get("type") == "mission_greeting"
    # 没有任何 user 消息（未触发 super）
    assert not [m for m in msgs if m.role == "user"]


async def test_goal_hint_blank_whitespace_treated_as_empty(
    seeded_client: AsyncClient, seeded_db: AsyncSession, super_agent_id
):
    """goal_hint 全是空白 → 视为没填，走问候语分支。"""
    auth = await _auth(seeded_client)
    mid = await _create_mission(seeded_client, auth, super_agent_id, goal_hint="   \n  ")

    msgs = await _main_messages(seeded_db, mid)
    assert len(msgs) == 1
    assert msgs[0].role == "assistant"
    assert not [m for m in msgs if m.role == "user"]
