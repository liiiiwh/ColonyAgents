"""ADR-025 · worker 修好后按 capability 自动唤醒所有等待者。

super 上报 worker 坏 → 停工 paused_waiting_capability(reason=worker_issue:<cap>)。
worker-opt 成功 apply 修复 → 按 capability 唤醒所有该等待者（确定性，不依赖人工/Builder）；
修不动 → 不唤醒（等后续轮次或 max-tick 收尾时处理）。
"""
from __future__ import annotations

import uuid

import pytest

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.services.worker_health_service import resume_waiters_for_capability

pytestmark = pytest.mark.asyncio


async def _mk_paused_reporter(db, *, capability: str) -> Mission:
    """建一个因 worker_issue:<cap> 停工的上报方 mission。"""
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
                   paused_reason=f"worker_issue:{capability}: data_fetcher 反复 500")
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def test_resume_waiters_for_capability_wakes_reporter(db_session):
    """修好 cap=data_fetcher → 该 capability 的停工上报方被唤醒回 running。"""
    rep = await _mk_paused_reporter(db_session, capability="data_fetcher")
    woken = await resume_waiters_for_capability(db_session, "data_fetcher")
    await db_session.refresh(rep)
    assert woken == 1
    assert rep.lifecycle_status == "running"


async def test_resume_only_matching_capability(db_session):
    """修 data_fetcher 不应唤醒等 report_writer 的 mission（capability 隔离 + 尾冒号防前缀撞）。"""
    fetcher = await _mk_paused_reporter(db_session, capability="data_fetcher")
    other = await _mk_paused_reporter(db_session, capability="report_writer")
    woken = await resume_waiters_for_capability(db_session, "data_fetcher")
    await db_session.refresh(fetcher)
    await db_session.refresh(other)
    assert woken == 1
    assert fetcher.lifecycle_status == "running"
    assert other.lifecycle_status == "paused_waiting_capability"  # 不受影响


# NOTE: agent_protocol_apply 成功后调 resume_waiters_for_capability 的 wiring（self_tune_skills.py）
# 无法在 sqlite 单测覆盖——apply 工具读 proposal.expires_at(DateTime(timezone=True)) 与
# datetime.now(UTC) 比较，sqlite 返回 naive 触发既有 TypeError（生产 Postgres 返回 aware 无此问题）。
# 核心 resume_waiters_for_capability 已被上面两个单测覆盖；apply→resume wiring 留 docker e2e 验证。
