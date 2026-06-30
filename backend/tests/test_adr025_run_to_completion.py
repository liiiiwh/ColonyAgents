"""ADR-025 D2 · work-order 跑到完成：续跑 / 软关闭 / max-tick 封顶。

- close_work_order：软关闭（STOP+archived）+ 按 capability 唤醒等待者 + 注销调度
- enqueue_continue：入队续跑；有未决 force_human 卡则拒绝（不越过人工门）
"""
from __future__ import annotations

import uuid

import pytest

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.services.worker_optimization_service import (
    close_work_order,
    enqueue_continue,
    maybe_cap_work_order,
    spawn_or_attach_work_order,
)

pytestmark = pytest.mark.asyncio


async def _mk_optsuper(db) -> tuple[Agent, User]:
    u = User(username=f"u-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@t.io",
             hashed_password="x")
    db.add(u)
    await db.flush()
    sup = Agent(name=f"opt-{uuid.uuid4().hex[:6]}", category="utility", kind="super",
                model_id=None, soul_md="x", protocol_md="x")
    db.add(sup)
    await db.commit()
    await db.refresh(sup)
    return sup, u


async def _mk_paused_reporter(db, *, capability: str) -> Mission:
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
                   lifecycle_status="paused_waiting_capability", runtime_status="stopped",
                   paused_reason=f"worker_issue:{capability}: 反复失败")
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def test_close_work_order_archives_and_wakes_waiters(db_session):
    """完成 → mission 软关闭(archived) + 按 capability 唤醒等待者。"""
    sup, u = await _mk_optsuper(db_session)
    wo, _ = await spawn_or_attach_work_order(
        db_session, super_agent_id=sup.id, created_by=u.id,
        capability="data_fetcher", worker_agent_id="w1", report="坏了",
    )
    # work-order 视为运行中
    wo.lifecycle_status = "running"
    wo.runtime_status = "running"
    await db_session.commit()
    rep = await _mk_paused_reporter(db_session, capability="data_fetcher")

    await close_work_order(db_session, wo.id, outcome="fixed")
    await db_session.refresh(wo)
    await db_session.refresh(rep)
    assert wo.status == "archived"
    assert rep.lifecycle_status == "running"  # 等待者被唤醒


# NOTE: enqueue_continue 的 happy-path（真入队）无法 sqlite 单测——super_pending_messages 是
# raw-SQL 表（无 ORM 模型 + Postgres now() 语法），测试库建不出。入队委托给全仓在用的
# pending_queue.enqueue_user_message（已被各处覆盖）；happy-path 留 docker e2e。守卫路径
# （下面）不碰队列、可单测，是安全关键项。


async def test_enqueue_continue_refuses_on_pending_approval(db_session):
    """有未决审批卡（auto 下=force_human 真人门）→ 拒绝入队，不越过人工门。"""
    from app.services.pending_approval_service import create_pending

    sup, u = await _mk_optsuper(db_session)
    wo, _ = await spawn_or_attach_work_order(
        db_session, super_agent_id=sup.id, created_by=u.id,
        capability="data_fetcher", worker_agent_id="w1", report="坏了",
    )
    wo.lifecycle_status = "running"
    await db_session.commit()
    await create_pending(
        db_session, mission_id=wo.id, title="不可逆操作需人工", message="...",
        options=["同意", "拒绝"], thread_key="main", dispatch_wechat=False,
    )
    res = await enqueue_continue(db_session, wo.id)
    assert res["enqueued"] is False
    assert res["reason"] == "pending_human_approval"


async def test_close_refuses_non_work_order(db_session):
    """自守卫：技能按 kind 绑所有 super，但 optimization_done 只能关 work-order——
    普通 super 误调不会关掉自己的 mission。"""
    sup, u = await _mk_optsuper(db_session)
    normal = Mission(name="普通", slug=f"n-{uuid.uuid4().hex[:8]}",
                     supervisor_agent_id=sup.id, created_by=u.id,
                     lifecycle_status="running", runtime_status="running")
    db_session.add(normal)
    await db_session.commit()
    res = await close_work_order(db_session, normal.id, outcome="fixed")
    await db_session.refresh(normal)
    assert res["ok"] is False
    assert res["error"] == "not_a_work_order"
    assert normal.status != "archived"  # 没被误关


async def test_max_tick_caps_unfinished_work_order(db_session):
    """跑到 max-tick 仍没收尾 → 强制软关闭(capped)，防无限重踢。"""
    sup, u = await _mk_optsuper(db_session)
    wo, _ = await spawn_or_attach_work_order(
        db_session, super_agent_id=sup.id, created_by=u.id,
        capability="data_fetcher", worker_agent_id="w1", report="修不动",
    )
    wo.lifecycle_status = "running"
    await db_session.commit()
    # 未到顶 → 不封顶
    assert await maybe_cap_work_order(db_session, wo.id, run_count=3, max_ticks=12) is False
    await db_session.refresh(wo)
    assert wo.status != "archived"
    # 到顶 → 强制收尾
    assert await maybe_cap_work_order(db_session, wo.id, run_count=12, max_ticks=12) is True
    await db_session.refresh(wo)
    assert wo.status == "archived"
