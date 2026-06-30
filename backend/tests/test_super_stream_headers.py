"""Part 3 · SSE 流式稳定性 · /api/super/{slug}/stream 防缓冲响应头。

tool call 在前端「一大块几十个蹦出来」而非逐个到达，根因之一是 HTTP 层（代理/中间件）
对 SSE 做了缓冲。daemon 侧已逐 piece publish（event_bus 实时），SSE relay 也逐事件 yield，
所以这里把 StreamingResponse 显式标注「别缓冲我」：
  - Cache-Control: no-cache, no-transform  （禁缓存 + 禁中间层 transform/压缩）
  - X-Accel-Buffering: no                   （nginx/反代不缓冲）
  - Connection: keep-alive
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def mission_slug(
    seeded_db: AsyncSession, db_engine, monkeypatch: pytest.MonkeyPatch
) -> str:
    """建一个 super agent + 一个 mission，返回 mission.slug 供 stream 端点解析。

    super_stream 的 gen() 用模块级 `AsyncSessionLocal` 开新 session（conftest 的
    _patched_session_local 改的是另一个模块属性，覆不到这里）→ 把它指向 seeded_db 同一
    in-memory engine（已 create_all 全表），否则 gen() 初始块查 pending_approvals 会
    "no such table"。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker
    import app.api.super_conversation as _sc

    monkeypatch.setattr(_sc, "AsyncSessionLocal", async_sessionmaker(db_engine, expire_on_commit=False))

    # super_pending_messages 是 raw-DDL 表，测试库没建 → mock count_pending（与
    # test_mission_goal_hint 同样的做法），避免 gen() 初始块 "no such table"。
    async def _zero_pending(_db, _mid):
        return 0

    monkeypatch.setattr(_sc.super_inbox, "count_pending", _zero_pending)

    # 让 live 订阅立即收尾（否则 gen() 会在首个 30s heartbeat 上空等，拖慢测试）。
    from app.services import event_bus as _eb

    async def _empty_sub(_channel):
        return
        yield  # pragma: no cover — 标记成 async generator

    monkeypatch.setattr(_eb.bus, "subscribe", _empty_sub)

    from app.models.agent import Agent
    from app.domain.builder.factory import spawn_mission
    from app.models.user import User
    from sqlalchemy import select

    sid = uuid.uuid4()
    seeded_db.add(Agent(
        id=sid, name=f"sup_{sid.hex[:6]}", slug=f"sup-{sid.hex[:6]}",
        display_name="Stream Super", kind="super", category="custom",
        model_id=uuid.uuid4(), soul_md="", protocol_md="",
    ))
    await seeded_db.commit()
    admin = (await seeded_db.execute(
        select(User).where(User.username == "admin")
    )).scalar_one()
    ref = await spawn_mission(
        seeded_db, super_agent_id=sid, name="Stream Mission", created_by=admin.id,
    )
    return ref.slug


async def test_super_stream_sets_anti_buffer_headers(
    seeded_client: AsyncClient, mission_slug: str
):
    async with seeded_client.stream("GET", f"/api/super/{mission_slug}/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        cache_control = resp.headers.get("cache-control", "")
        assert "no-cache" in cache_control, cache_control
        assert "no-transform" in cache_control, cache_control
        assert resp.headers.get("x-accel-buffering") == "no"
