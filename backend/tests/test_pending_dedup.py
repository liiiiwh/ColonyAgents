"""S2 · 审批未决去重（ADR-024 #2）。

同一 (mission, thread) 同时只允许一个未决审批——审批是阻塞串行的，LLM 每次措辞不同
所以不能按 title 去重。已有 pending 时 create_pending 复用、不新建，杜绝「没审批又跑一次冒新卡」。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models.agent import Agent
from app.models.approvals import PendingApproval
from app.models.mission import Mission
from app.models.user import User
from app.services.pending_approval_service import create_pending

pytestmark = pytest.mark.asyncio


async def _mk_mission(db) -> Mission:
    u = User(username=f"u-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@t.io",
             hashed_password="x")
    db.add(u)
    await db.flush()
    ag = Agent(name=f"sup-{uuid.uuid4().hex[:6]}", category="custom", kind="super",
               model_id=None, soul_md="x", protocol_md="x")
    db.add(ag)
    await db.flush()
    proj = Mission(name="m", slug=f"m-{uuid.uuid4().hex[:8]}",
                   supervisor_agent_id=ag.id, created_by=u.id)
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def test_create_pending_dedups_same_thread(db_session):
    """同 (mission, thread) 已有未决审批 → 第二次复用同一行，不叠加。"""
    proj = await _mk_mission(db_session)
    r1 = await create_pending(
        db_session, mission_id=proj.id, title="确认方案 A", message="...",
        options=["同意", "拒绝"], thread_key="main", dispatch_wechat=False,
    )
    r2 = await create_pending(
        db_session, mission_id=proj.id, title="确认方案 B（措辞不同）", message="...",
        options=["好", "不好"], thread_key="main", dispatch_wechat=False,
    )
    assert r2.request_id == r1.request_id  # 复用，未新建
    cnt = (await db_session.execute(
        select(func.count()).select_from(PendingApproval).where(
            PendingApproval.mission_id == proj.id,
            PendingApproval.status == "pending",
        )
    )).scalar()
    assert cnt == 1


async def test_create_pending_allows_after_decided(db_session):
    """前一个审批已 decided 后，可再创建新审批（去重只针对未决）。"""
    proj = await _mk_mission(db_session)
    r1 = await create_pending(
        db_session, mission_id=proj.id, title="A", message="...",
        options=["x", "y"], thread_key="main", dispatch_wechat=False,
    )
    r1.status = "decided"
    await db_session.commit()
    r2 = await create_pending(
        db_session, mission_id=proj.id, title="B", message="...",
        options=["x", "y"], thread_key="main", dispatch_wechat=False,
    )
    assert r2.request_id != r1.request_id  # 旧的已决，新的正常创建
