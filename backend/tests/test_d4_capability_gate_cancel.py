"""ADR-028 D4 · H1 收尾 · 缺能力/worker坏 也是人工门 → 硬停当前 tick。

补 workflow verify 抓到的缺口：request_new_capability / report_worker_issue 落
paused_waiting_capability 后必须 set cancel_event（cooperative 硬停），不只 force_human 审批。
+ H6 墙钟封顶纯函数。
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.skills_builtin.context import BuiltinToolContext

pytestmark = pytest.mark.asyncio


async def _mk_running_mission(db) -> uuid.UUID:
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
    return proj.id


class _FakeTool:
    """伪 escalate StructuredTool：.coroutine 直接返回成功 json。"""
    @staticmethod
    async def coroutine(**kw):
        return json.dumps({"ok": True, "status": "queued"})


async def test_request_new_capability_sets_cancel_event(
    db_session, _patched_session_local, monkeypatch
):
    mid = await _mk_running_mission(db_session)

    import app.skills_builtin.super.super_dispatch_skills as sds
    from app.skills_builtin.builder import escalation_skills
    monkeypatch.setattr(escalation_skills, "mission_escalate_to_builder_tool", lambda ctx: _FakeTool())

    from app.db.session import AsyncSessionLocal
    ev = asyncio.Event()
    ctx = BuiltinToolContext(mission_id=mid, db_factory=AsyncSessionLocal, cancel_event=ev,
                             extra={"agent_id": str(uuid.uuid4())})
    tool = sds.request_new_capability_tool(ctx)
    res = json.loads(await tool.coroutine(capability="xhs_publisher", why="需要发帖能力"))

    assert res.get("ok") is True and res.get("super_paused") is True, res
    assert ev.is_set(), "缺能力落人工门后必须 set cancel_event 硬停当前 tick (H1)"


def test_tick_wallclock_exceeded():
    from app.domain.tick_policy import tick_wallclock_exceeded
    assert tick_wallclock_exceeded(elapsed_s=901, cap_s=900) is True
    assert tick_wallclock_exceeded(elapsed_s=10, cap_s=900) is False
    assert tick_wallclock_exceeded(elapsed_s=99999, cap_s=0) is False  # cap<=0 不限
