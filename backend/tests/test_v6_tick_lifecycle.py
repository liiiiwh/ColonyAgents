"""R4-5 · super_inbox 拆分 · tick_lifecycle（in-memory registry + cancel）与 pending_queue（DB）分家。

本测试锁 tick_lifecycle 的纯 in-memory 行为（无需 DB）。
super_inbox 保留 re-export，老 caller 不变。
"""
from __future__ import annotations

import asyncio
import uuid

import pytest


def test_register_makes_is_running_true_until_unregister():
    from app.services.tick_lifecycle import register_task, unregister_task, is_running

    pid = uuid.uuid4()
    assert is_running(pid) is False

    async def _noop():
        await asyncio.sleep(3600)

    loop = asyncio.new_event_loop()
    task = loop.create_task(_noop())
    register_task(pid, task)
    assert is_running(pid) is True
    unregister_task(pid)
    assert is_running(pid) is False
    task.cancel()
    loop.close()


def test_get_cancel_event_stable_identity():
    from app.services.tick_lifecycle import get_cancel_event

    pid = uuid.uuid4()
    ev1 = get_cancel_event(pid)
    ev2 = get_cancel_event(pid)
    assert ev1 is ev2


def test_register_clears_stale_cancel_event():
    """新 tick register 时，若 cancel_event 之前被 set 过，应 clear（新 tick 不该一开始就被 cancel）。"""
    from app.services.tick_lifecycle import register_task, get_cancel_event

    pid = uuid.uuid4()
    ev = get_cancel_event(pid)
    ev.set()
    assert ev.is_set()

    async def _noop():
        await asyncio.sleep(3600)

    loop = asyncio.new_event_loop()
    task = loop.create_task(_noop())
    register_task(pid, task)
    assert not ev.is_set(), "register 应 clear 旧 cancel_event"
    task.cancel()
    loop.close()


@pytest.mark.asyncio
async def test_cancel_from_within_own_tick_only_signals():
    """ADR-028 D4 · H1：人工门 skill 在 tick 任务自身内调 cancel_current_tick →
    只 set cancel_event（self_signal），不 await 自己（否则死锁/被强 cancel）。"""
    from app.services.tick_lifecycle import (
        register_task, get_cancel_event, cancel_current_tick, unregister_task,
    )

    pid = uuid.uuid4()
    result_holder: dict = {}

    async def _tick_body():
        register_task(pid, asyncio.current_task())
        ev = get_cancel_event(pid)
        assert not ev.is_set()
        # 模拟人工门 skill 在 tick 内落卡 → cancel 自己
        result_holder["res"] = await cancel_current_tick(pid)
        assert ev.is_set(), "self_signal 应 set cancel_event"
        unregister_task(pid)

    await asyncio.wait_for(_tick_body(), timeout=2.0)
    assert result_holder["res"]["stage"] == "self_signal"


def test_super_inbox_reexports_tick_lifecycle():
    """向后兼容：super_inbox.register_task / is_running / get_cancel_event 仍可用。"""
    from app.services import super_inbox
    assert hasattr(super_inbox, "register_task")
    assert hasattr(super_inbox, "is_running")
    assert hasattr(super_inbox, "get_cancel_event")
    assert hasattr(super_inbox, "cancel_current_tick")


def test_super_inbox_reexports_pending_queue():
    from app.services import super_inbox
    assert hasattr(super_inbox, "enqueue_user_message")
    assert hasattr(super_inbox, "pop_pending_messages")
    assert hasattr(super_inbox, "count_pending")


def test_tick_lifecycle_and_pending_queue_are_separate_modules():
    """拆分后两个 concern 在不同模块。"""
    from app.services import tick_lifecycle, pending_queue
    assert hasattr(tick_lifecycle, "cancel_current_tick")
    assert hasattr(pending_queue, "enqueue_user_message")
    # tick_lifecycle 不该有队列 CRUD
    assert not hasattr(tick_lifecycle, "enqueue_user_message")
