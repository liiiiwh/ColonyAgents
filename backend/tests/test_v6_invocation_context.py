"""R3-2 · InvocationContext · super↔worker 持久对话的代码家。

CONTEXT.md 命名 InvocationContext = super↔worker 持久对话。之前散成 3 截：
- _THREAD_LOCKS module-global dict (V53)
- _get_or_create_super_worker_thread (line 151)
- __load_thread_messages (line 646, 相隔 430 LOC)

收进一个 class：lock 实例持有 + branch resolve + history load。行为不变。
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def test_same_super_worker_pair_shares_lock():
    """V53 不变式：同一 (super, worker) 对拿到同一把 Lock（并发 invoke 串行化）。"""
    from app.domain.dispatch.invocation_context import InvocationContext

    sid = uuid.uuid4()
    wid = uuid.uuid4()
    ic1 = InvocationContext(db=None, super_session_id=uuid.uuid4(), super_id=sid, worker_id=wid)
    ic2 = InvocationContext(db=None, super_session_id=uuid.uuid4(), super_id=sid, worker_id=wid)
    assert ic1.thread_lock is ic2.thread_lock, "同 super+worker 必须共享同一把锁"


def test_different_worker_gets_different_lock():
    from app.domain.dispatch.invocation_context import InvocationContext

    sid = uuid.uuid4()
    ic1 = InvocationContext(db=None, super_session_id=uuid.uuid4(), super_id=sid, worker_id=uuid.uuid4())
    ic2 = InvocationContext(db=None, super_session_id=uuid.uuid4(), super_id=sid, worker_id=uuid.uuid4())
    assert ic1.thread_lock is not ic2.thread_lock


@pytest.mark.asyncio
async def test_acquire_is_async_context_manager_holding_lock():
    """acquire() 是 async context manager；进入时持锁，退出释放。"""
    from app.domain.dispatch.invocation_context import InvocationContext

    sid, wid = uuid.uuid4(), uuid.uuid4()
    ic = InvocationContext(db=None, super_session_id=uuid.uuid4(), super_id=sid, worker_id=wid)
    assert not ic.thread_lock.locked()
    async with ic.acquire():
        assert ic.thread_lock.locked()
    assert not ic.thread_lock.locked()


@pytest.mark.asyncio
async def test_thread_id_naming_convention():
    """thread_id(=thread_key) 命名 worker:{super_id}:{worker_id}（全 UUID，ADR-020）。"""
    from app.domain.dispatch.invocation_context import InvocationContext

    sid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    wid = uuid.UUID("22222222-2222-2222-2222-222222222222")
    ic = InvocationContext(db=None, super_session_id=uuid.uuid4(), super_id=sid, worker_id=wid)
    assert ic.thread_id == f"worker:{sid}:{wid}"
