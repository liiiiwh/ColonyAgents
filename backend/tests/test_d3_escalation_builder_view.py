"""ADR-028 D3 · 缺能力升级闭环（Builder 视角）。

Builder 用 `_count_unresolved` / `mission_escalation_list` 时，要看到的是
**所有由它产出的 super（agent.built_by_mission_id == 本 builder mission）投回的升级**，
而不是「本 builder mission 自己发的 escalation（escalation.mission_id == 本 mission）」。

造两个 mission：
- builder_mission（supervisor = builder_agent）
- super_mission（supervisor = super_agent，super_agent.built_by_mission_id = builder_mission）
super 发一条 escalation（mission_id = super_mission），断言 Builder 视角能查到 + count>0。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.models.agent import Agent
from app.models.mission import Mission, MissionEscalation
from app.models.user import User
from app.skills_builtin.builder.escalation_skills import (
    _count_unresolved,
    mission_escalation_list_tool,
)
from app.skills_builtin.context import BuiltinToolContext


async def _seed_builder_super_escalation(db):
    """builder_mission 产出 super；super 发一条 pending escalation。返回 (builder_mission, super_mission, esc)。"""
    user = User(username="u", email="u@x.com", hashed_password="x", role="admin")
    builder_agent = Agent(name="Builder Supervisor", category="builder", kind="super", slug="builder")
    db.add_all([user, builder_agent])
    await db.flush()
    builder_mission = Mission(
        name="设计会话", slug="builder-mission", supervisor_agent_id=builder_agent.id,
        created_by=user.id, workflow_config={},
    )
    db.add(builder_mission)
    await db.flush()
    # 由 builder_mission 产出的 super（provenance）
    super_agent = Agent(
        name="logi-super", kind="super", category="custom", slug="logi",
        built_by_mission_id=builder_mission.id,
    )
    db.add(super_agent)
    await db.flush()
    super_mission = Mission(
        name="物流运行", slug="logi-run", supervisor_agent_id=super_agent.id,
        created_by=user.id, workflow_config={},
    )
    db.add(super_mission)
    await db.flush()
    esc = MissionEscalation(
        mission_id=super_mission.id, created_at=datetime.now(UTC), category="structural",
        severity="warn", summary="缺『跨区域调拨审批』能力",
        proposed_change="新建 dispatch_approver worker", fingerprint="fp-d3-1", status="pending",
    )
    db.add(esc)
    await db.commit()
    return builder_mission, super_mission, esc


@pytest.mark.asyncio
async def test_count_unresolved_sees_super_escalations_by_built_by(db_session):
    builder_mission, super_mission, esc = await _seed_builder_super_escalation(db_session)

    # Builder 视角：用自己的 builder_mission.id 查，应看到 super 投回的 1 条
    n = await _count_unresolved(db_session, builder_mission.id)
    assert n == 1, "Builder 应能按 built_by_mission_id 看到 super 投回的未处理升级"

    # 反向：用 super_mission.id 当「builder mission」查，不该把 super 自己当成它产出的 super
    n_super = await _count_unresolved(db_session, super_mission.id)
    assert n_super == 0, "super_mission 没有产出任何 super，count 应为 0"


@pytest.mark.asyncio
async def test_count_unresolved_excludes_acted(db_session):
    builder_mission, super_mission, esc = await _seed_builder_super_escalation(db_session)
    esc.status = "acted"
    await db_session.commit()
    n = await _count_unresolved(db_session, builder_mission.id)
    assert n == 0, "acted 状态不算未处理"


@pytest.mark.asyncio
async def test_mission_escalation_list_builder_view(db_session, _patched_session_local):
    builder_mission, super_mission, esc = await _seed_builder_super_escalation(db_session)

    ctx = BuiltinToolContext(mission_id=builder_mission.id, db_factory=_patched_session_local)
    tool = mission_escalation_list_tool(ctx)
    out = json.loads(await tool.coroutine())
    ids = {r["id"] for r in out}
    assert str(esc.id) in ids, "Builder 的 escalation_list 应列出投递给它的 super 升级"
    assert len(out) == 1


@pytest.mark.asyncio
async def test_mission_escalation_list_only_open_filter(db_session, _patched_session_local):
    builder_mission, super_mission, esc = await _seed_builder_super_escalation(db_session)
    esc.status = "dismissed"
    await db_session.commit()

    ctx = BuiltinToolContext(mission_id=builder_mission.id, db_factory=_patched_session_local)
    tool = mission_escalation_list_tool(ctx)
    # only_open=True（默认）→ dismissed 不出现
    out_open = json.loads(await tool.coroutine(only_open=True))
    assert out_open == []
    # only_open=False → 全部
    out_all = json.loads(await tool.coroutine(only_open=False))
    assert {r["id"] for r in out_all} == {str(esc.id)}
