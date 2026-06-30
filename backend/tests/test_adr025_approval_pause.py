"""ADR-025 D3 · 审批暂停全平台不变式。

不变式：存在 pending 审批卡 ⟺ mission `paused_clarification`，且至多一张卡。
- 落卡 → pause（调度器/cron 跳过暂停态）
- 答卡（decide）→ resume → running
- 用户发消息 → 旧卡关闭置灰 + resume → running
- auto 模式普通审批瞬时通过、不落卡 → 不暂停
"""
from __future__ import annotations

import uuid

import pytest

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.services.mission_daemon import _should_skip_tick
from app.services.pending_approval_service import create_pending, decide

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


async def test_create_pending_pauses_mission(db_session):
    """落 pending 卡 → mission 进入 paused_clarification（不再被调度 tick）。"""
    proj = await _mk_running_mission(db_session)
    await create_pending(
        db_session, mission_id=proj.id, title="需人工拍板", message="...",
        options=["同意", "拒绝"], thread_key="main", dispatch_wechat=False,
    )
    await db_session.refresh(proj)
    assert proj.lifecycle_status == "paused_clarification"


async def test_decide_resumes_mission(db_session):
    """答卡（decide）→ mission resolve_clarification 回 running，可续跑。"""
    proj = await _mk_running_mission(db_session)
    row = await create_pending(
        db_session, mission_id=proj.id, title="需人工拍板", message="...",
        options=["同意", "拒绝"], thread_key="main", dispatch_wechat=False,
    )
    await db_session.refresh(proj)
    assert proj.lifecycle_status == "paused_clarification"

    await decide(db_session, request_id=row.request_id, option="同意", decided_by="tester")
    await db_session.refresh(proj)
    assert proj.lifecycle_status == "running"


async def test_skip_tick_on_paused_clarification(db_session):
    """调度器/cron tick：mission 处于 paused_clarification → _should_skip_tick 跳过。"""
    proj = await _mk_running_mission(db_session)
    proj.lifecycle_status = "paused_clarification"
    proj.runtime_status = "running"
    await db_session.commit()
    reason, _detail = await _should_skip_tick(
        db_session, proj.id, proj, {"trigger": "cron"},
    )
    assert reason == "paused_clarification"


async def test_request_approval_must_human_pauses(db_session, _patched_session_local, monkeypatch):
    """ADR-028 D1（修订）· approval_judge 判 must_human=True → request_approval 落卡 + 暂停
    （super 不再传 force_human；判定来自服务端 approval_judge）。"""
    from app.db.session import AsyncSessionLocal
    from app.skills_builtin.context import BuiltinToolContext
    from app.skills_builtin.super.supervisor_skills import request_approval_tool
    from app.services import approval_judge_service

    async def _judge_human(db, mission, **kw):
        return True, "user required manual review"
    monkeypatch.setattr(approval_judge_service, "judge_must_human", _judge_human)

    proj = await _mk_running_mission(db_session)
    ctx = BuiltinToolContext(mission_id=proj.id, thread_key="main",
                             agent_node_name="sup", db_factory=AsyncSessionLocal)
    await request_approval_tool(ctx).coroutine(
        title="是否上线？", message="...", options=["同意", "拒绝"],
        context="发布前用户要求必须人工确认",
    )
    await db_session.refresh(proj)
    assert proj.lifecycle_status == "paused_clarification"


async def test_auto_approve_does_not_pause(db_session, _patched_session_local):
    """回归：auto 模式（force_auto_approve）普通审批瞬时通过、不落卡 → mission 不暂停。

    护住所有 auto-run mission（worker-opt / auto_approve）：普通审批绝不能把它们卡住。"""
    from app.db.session import AsyncSessionLocal
    from app.skills_builtin.context import BuiltinToolContext
    from app.skills_builtin.super.supervisor_skills import request_approval_tool

    proj = await _mk_running_mission(db_session)
    ctx = BuiltinToolContext(mission_id=proj.id, thread_key="main", agent_node_name="sup",
                             db_factory=AsyncSessionLocal, extra={"force_auto_approve": True})
    await request_approval_tool(ctx).coroutine(
        title="例行确认", message="...", options=["继续", "取消"],  # 不带 force_human
    )
    await db_session.refresh(proj)
    assert proj.lifecycle_status == "running"


async def test_decide_schedules_continuation_even_when_tick_running(db_session, monkeypatch):
    """ADR-028 fix · decide 时若有 in-flight（正被 cancel）tick 仍占用 super_inbox（is_running=True），
    旧逻辑 should_trigger_now=False → 直接丢掉续跑触发 → 确认建造后构建永不继续（用户反复投诉的
    「审批决了没继续处理」卡死，本轮 Chrome e2e 真实复现）。修复：decide 在 mission 可恢复时
    **无条件**调度续跑触发（触发器自身 wait-for-idle 去重，run_once 的 _TICKING 守卫兜底防重跑）。"""
    proj = await _mk_running_mission(db_session)
    row = await create_pending(
        db_session, mission_id=proj.id, title="确认方案？", message="...",
        options=["Confirm, start building", "Let me adjust"], thread_key="main",
        dispatch_wechat=False,
    )
    await db_session.refresh(proj)
    assert proj.lifecycle_status == "paused_clarification"

    # 模拟 propose-tick 仍在 super_inbox 注册（被 cancel 中、尚未 unregister）→ is_running=True
    from app.services import super_inbox
    monkeypatch.setattr(super_inbox, "is_running", lambda *a, **k: True)

    scheduled: list[str | None] = []
    import app.core.bg_tasks as bg

    def _fake_spawn(coro, name=None):  # noqa: ANN001
        scheduled.append(name)
        coro.close()  # 不真跑，避免 DB/async 副作用
        return None

    monkeypatch.setattr(bg, "spawn", _fake_spawn)

    await decide(
        db_session, request_id=row.request_id,
        option="Confirm, start building", decided_by="inline-card",
    )
    await db_session.refresh(proj)
    assert proj.lifecycle_status == "running"  # 已恢复
    assert any(n and "tick" in n for n in scheduled), (
        f"decide 必须在 in-flight tick（is_running=True）下仍调度续跑触发，实际 scheduled={scheduled}"
    )


async def test_create_pending_publishes_approval_request_event(db_session, monkeypatch):
    """ADR-028 fix · 落卡时**实时**向 event_bus 推 approval_request（前端 SSE 处理器已存在，
    但后端从不 emit → mid-session 创建的卡只能靠刷新 REST 兜底拉到，未刷新时渲染成「已关闭」
    不可点，人工审批被堵死，Chrome e2e 真实复现）。修复：create_pending 落卡后 publish。"""
    from app.services.event_bus import bus

    published: list[dict] = []

    async def _fake_publish(channel, evt):  # noqa: ANN001
        published.append({"channel": channel, **evt})

    monkeypatch.setattr(bus, "publish", _fake_publish)

    proj = await _mk_running_mission(db_session)
    row = await create_pending(
        db_session, mission_id=proj.id, title="确认方案？", message="...",
        options=["Confirm", "Adjust"], thread_key="main", dispatch_wechat=False,
    )

    reqs = [e for e in published if e.get("type") == "approval_request"]
    assert reqs, f"create_pending 必须 publish approval_request，实际事件={[e.get('type') for e in published]}"
    evt = reqs[0]
    assert evt["channel"] == proj.id
    assert evt["request_id"] == row.request_id
    assert evt["options"] == ["Confirm", "Adjust"]
