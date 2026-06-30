"""心跳 sweeper 健壮性：注册表里有「mission 已被删」的僵尸 daemon 时不能拖垮全平台。

回归 bug：F7 清理删掉 wo-% mission 后，其 daemon 仍留在进程内 _DAEMONS。心跳 sweep 每
30s 给它 _get_or_create_run_state → INSERT mission_run_state 命中 FK（mission 没了）→
IntegrityError 污染共享 session → 同一轮后续所有 mission 的心跳也写不进 → reconcile 把
全平台 mission 误标 error。

不变式：
- mission 已删的 daemon → 本轮 sweep 把它从 _DAEMONS 摘除（不再每 30s 重试）。
- 摘僵尸 daemon 不影响同轮真实 mission 的心跳写入（session 不被污染）。
"""
from __future__ import annotations

import uuid

import pytest

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.services import mission_daemon as md

pytestmark = pytest.mark.asyncio


async def _mk_running_mission(db) -> Mission:
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
                   lifecycle_status="running", runtime_status="running")
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def test_sweep_deregisters_daemon_whose_mission_is_gone(db_session):
    """注册一个不存在 mission 的僵尸 daemon → 一轮 sweep 后它被摘除，且不抛异常。"""
    ghost = uuid.uuid4()  # 从不写进 missions 表
    md._DAEMONS[ghost] = md._DaemonEntry(started_at=md.datetime.now(md.UTC))
    try:
        deregistered = await md._heartbeat_sweep_pass(db_session, [ghost])
        assert ghost in deregistered
        assert ghost not in md._DAEMONS  # 僵尸已摘除，不再每 30s 重试
    finally:
        md._DAEMONS.pop(ghost, None)


async def test_ghost_daemon_does_not_poison_real_mission_heartbeat(db_session):
    """同一轮 sweep 里：僵尸 daemon 在前、真实 mission 在后 → 真实 mission 心跳照常写入。"""
    ghost = uuid.uuid4()
    real = await _mk_running_mission(db_session)
    md._DAEMONS[ghost] = md._DaemonEntry(started_at=md.datetime.now(md.UTC))
    md._DAEMONS[real.id] = md._DaemonEntry(started_at=md.datetime.now(md.UTC))
    try:
        # 僵尸排在前面，若 session 被污染则真实 mission 的心跳会连带失败
        await md._heartbeat_sweep_pass(db_session, [ghost, real.id])
        rs = await md._get_or_create_run_state(db_session, real.id)
        assert rs.last_heartbeat_at is not None  # 真实 mission 心跳成功落库
    finally:
        md._DAEMONS.pop(ghost, None)
        md._DAEMONS.pop(real.id, None)
