"""重启后 reconcile：lifecycle=running 的 mission 应**自动续跑**，而不是一律标 error。

背景：`docker restart` / SIGKILL 后 daemon 没优雅退出，心跳变陈旧。旧 reconcile_on_boot
把所有 running/starting/stopping 且心跳过期的 mission 一律标 runtime_status=error → 后台
所有 super 显示「error / 暂无运营」，每次重启都要人工逐个点「启动」。

新行为（用户选「启动时自动续跑」）：
- lifecycle_status='running'（FSM 认为该运行、非暂停）→ 自动重新拉起 daemon（resume），
  runtime_status 回到 running、心跳刷新。
- paused_*（pending_approval / waiting_capability）等 → 维持原行为标 error，**不**自动续跑。
"""
from __future__ import annotations

import uuid

import pytest

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.services import mission_daemon as md

pytestmark = pytest.mark.asyncio


async def _mk_mission(db, *, lifecycle: str) -> Mission:
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
                   lifecycle_status=lifecycle, runtime_status="running")
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    # 制造陈旧心跳：last_heartbeat 远早于 cutoff
    rs = await md._get_or_create_run_state(db, proj.id)
    rs.status = "running"
    rs.last_heartbeat_at = md.datetime.now(md.UTC) - md.timedelta(seconds=md.STALE_HEARTBEAT_SEC + 60)
    await db.commit()
    return proj


async def test_reconcile_resumes_running_mission(db_session, _patched_session_local):
    """lifecycle=running + 心跳过期 → reconcile 自动续跑（runtime=running、入 _DAEMONS）。"""
    proj = await _mk_mission(db_session, lifecycle="running")
    try:
        await md.reconcile_on_boot()
        await db_session.refresh(proj)
        assert proj.runtime_status == "running", "lifecycle=running 的 mission 应被自动续跑而非标 error"
        assert proj.id in md._DAEMONS, "应重新注册 daemon"
    finally:
        md._DAEMONS.pop(proj.id, None)


async def test_reconcile_resumes_already_error_running_mission(db_session, _patched_session_local):
    """遗留场景：上一次旧 reconcile 已把 lifecycle=running 的 mission 标成 runtime=error。
    新 boot reconcile 仍应按 FSM 意图把它重新拉起（boot 时本就无 live daemon）。"""
    proj = await _mk_mission(db_session, lifecycle="running")
    proj.runtime_status = "error"  # 模拟旧 reconcile 留下的残留 error
    await db_session.commit()
    try:
        await md.reconcile_on_boot()
        await db_session.refresh(proj)
        assert proj.runtime_status == "running", "lifecycle=running 的 mission（哪怕残留 error）应被恢复"
        assert proj.id in md._DAEMONS
    finally:
        md._DAEMONS.pop(proj.id, None)


async def test_reconcile_does_not_resume_paused_mission(db_session, _patched_session_local):
    """paused_clarification + 心跳过期 → 不自动续跑，维持标 error（等人处理）。"""
    proj = await _mk_mission(db_session, lifecycle="paused_clarification")
    try:
        await md.reconcile_on_boot()
        await db_session.refresh(proj)
        assert proj.id not in md._DAEMONS, "暂停态 mission 不应被自动续跑"
        assert proj.runtime_status == "error"
    finally:
        md._DAEMONS.pop(proj.id, None)
