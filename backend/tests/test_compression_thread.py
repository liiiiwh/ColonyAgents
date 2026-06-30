"""ADR-018 Slice K: 压缩状态 → thread_compression_state。

压缩按 (mission_id, thread_key) 工作：消息选择、水位线、CAS 派发锁、熔断、thread 级 config
都挂在 thread_compression_state 上；压缩产出的摘要写 ThreadAgentMemory。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.message import (
    Message,
    ThreadAgentMemory,
    ThreadCompressionState,
)
from app.models.user import User
from app.services import compression_service, memory_service, messaging_service

pytestmark = pytest.mark.asyncio


async def _mk_mission(db) -> Mission:
    u = User(
        username=f"u-{uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:6]}@t.io",
        hashed_password="x",
    )
    db.add(u)
    await db.flush()
    ag = Agent(
        name=f"sup-{uuid.uuid4().hex[:6]}",
        category="custom",
        kind="super",
        model_id=None,
        soul_md="x",
        protocol_md="x",
    )
    db.add(ag)
    await db.flush()
    proj = Mission(
        name="m",
        slug=f"m-{uuid.uuid4().hex[:8]}",
        supervisor_agent_id=ag.id,
        created_by=u.id,
    )
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def test_maybe_compress_context_keyed_by_thread(db_session):
    """超阈值时按 (mission_id, thread_key) 压缩：写 ThreadAgentMemory + 标记消息 + 落水位线。"""
    proj = await _mk_mission(db_session)
    mission_id, thread_key = proj.id, "main"

    for i in range(6):
        await messaging_service.append_message(
            db_session, mission_id, thread_key, "user", f"问题 {i} " * 30, publish=False
        )
        await messaging_service.append_message(
            db_session, mission_id, thread_key, "assistant", f"回答 {i} " * 30, publish=False
        )

    mem = await compression_service.maybe_compress_context(
        db_session, mission_id, thread_key, "supervisor",
        threshold_tokens=10, keep_recent=2,
    )

    assert mem is not None
    assert isinstance(mem, ThreadAgentMemory)
    assert mem.memory_md.strip()

    # 水位线落在 thread_compression_state
    state = (
        await db_session.execute(
            select(ThreadCompressionState).where(
                ThreadCompressionState.mission_id == mission_id,
                ThreadCompressionState.thread_key == thread_key,
            )
        )
    ).scalar_one_or_none()
    assert state is not None
    assert state.compressed_up_to_at is not None

    # 大部分消息已标 is_compressed（保留最近 keep_recent=2 条）
    compressed = (
        await db_session.execute(
            select(Message).where(
                Message.mission_id == mission_id,
                Message.thread_key == thread_key,
                Message.is_compressed.is_(True),
            )
        )
    ).scalars().all()
    assert len(compressed) >= 8


# ── ADR-020 · 压缩 re-wire 的读回键一致性（防 daemon/worker 压缩后 super 读不到=静默丢上下文）──

async def test_main_compression_key_matches_supervisor_read(db_session):
    """daemon 用 node='supervisor' 压缩主线 → agent_service assemble 按 ctx.agent_node_name
    ='supervisor' 读回，键必须一致。"""
    proj = await _mk_mission(db_session)
    mid = proj.id
    for i in range(6):
        await messaging_service.append_message(db_session, mid, "main", "user", f"q{i} " * 30, publish=False)
        await messaging_service.append_message(db_session, mid, "main", "assistant", f"a{i} " * 30, publish=False)
    await compression_service.maybe_compress_context(
        db_session, mid, "main", "supervisor", threshold_tokens=10, keep_recent=2,
    )
    mem = await memory_service.get_thread_memory(db_session, mid, "main", "supervisor")
    assert mem is not None and mem.memory_md.strip()


async def test_worker_compression_readable_by_load_history(db_session):
    """invoke_worker 用 node='worker_conversation' 压缩 worker 线 → InvocationContext.load_history
    按同键读回并作 SystemMessage 注入。"""
    from langchain_core.messages import SystemMessage

    from app.domain.dispatch.invocation_context import InvocationContext

    proj = await _mk_mission(db_session)
    mid = proj.id
    ic = InvocationContext(db_session, super_session_id=mid, super_id=uuid.uuid4(), worker_id=uuid.uuid4())
    tk = ic.thread_id  # worker:{super}:{worker}
    for i in range(6):
        await messaging_service.append_message(db_session, mid, tk, "user", f"q{i} " * 30, publish=False)
        await messaging_service.append_message(db_session, mid, tk, "assistant", f"a{i} " * 30, publish=False)
    await compression_service.maybe_compress_context(
        db_session, mid, tk, "worker_conversation", threshold_tokens=10, keep_recent=2,
    )
    hist = await ic.load_history(mid, tk)
    assert any(
        isinstance(m, SystemMessage) and "thread_history_compressed" in (m.content or "")
        for m in hist
    )
