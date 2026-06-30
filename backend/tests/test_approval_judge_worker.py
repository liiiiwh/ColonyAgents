"""ADR-028 D1 · 系统级 approval_judge worker + 默认 super 协议硬门。

approval_judge 是平台唯一的「可自动 vs 必须人工」判定 worker（系统对象，不可删）：
- capability='approval_judge', kind='worker', is_system=True
- 协议集中写三硬停点：①Agent 完全无法自动继续 ②运行阻塞 ③人类要求必须人工审核 → must_human=True
- 输出结构化 {must_human, reason}

super 在 request_approval 前先 invoke_worker(capability:approval_judge) 拿 must_human，
再 request_approval(force_human=must_human)。这条规则写进：
- Builder super-design 协议（system_agent_prompts / init_db Builder protocol）
- mission_create 自动建 super 的默认 protocol_md（builder_skills）
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.init_db import seed_admin_user, seed_builder_project
from app.models.agent import Agent


@pytest.mark.asyncio
async def test_approval_judge_worker_seeded(db_session):
    await seed_admin_user(db_session)
    await seed_builder_project(db_session)

    judge = (await db_session.execute(
        select(Agent).where(Agent.capability == "approval_judge")
    )).scalar_one()

    assert judge.kind == "worker", "approval_judge 必须是 worker"
    assert judge.is_system is True, "approval_judge 必须是系统对象（不可删）"


@pytest.mark.asyncio
async def test_approval_judge_protocol_lists_three_hard_stops(db_session):
    await seed_admin_user(db_session)
    await seed_builder_project(db_session)

    judge = (await db_session.execute(
        select(Agent).where(Agent.capability == "approval_judge")
    )).scalar_one()

    proto = judge.protocol_md or ""
    # 三硬停点 + must_human / reason 结构化输出关键字
    assert "must_human" in proto
    assert "reason" in proto


@pytest.mark.asyncio
async def test_approval_judge_advertises_capability_contract(db_session):
    await seed_admin_user(db_session)
    await seed_builder_project(db_session)

    judge = (await db_session.execute(
        select(Agent).where(Agent.capability == "approval_judge")
    )).scalar_one()

    contract = (judge.extra_config or {}).get("capability_contract")
    assert contract is not None, "approval_judge 必须有 capability_contract（否则 super 无法 dispatch）"
    assert contract.get("capability") == "approval_judge"
    advertises = contract.get("advertises") or []
    assert any(a.get("action") == "judge" for a in advertises), "必须 advertise 'judge' action"
    # judge 本身不需要审批（否则递归）
    judge_action = next(a for a in advertises if a.get("action") == "judge")
    assert judge_action.get("requires_approval") is False
    out = judge_action.get("output_schema") or {}
    assert "must_human" in out and "reason" in out


@pytest.mark.asyncio
async def test_approval_judge_idempotent_reseed(db_session):
    """重复 seed 不应重复建 approval_judge worker。"""
    await seed_admin_user(db_session)
    await seed_builder_project(db_session)
    await seed_builder_project(db_session)

    judges = (await db_session.execute(
        select(Agent).where(Agent.capability == "approval_judge")
    )).scalars().all()
    assert len(judges) == 1, "approval_judge 必须幂等，不可重复 seed"


@pytest.mark.asyncio
async def test_builder_supervisor_protocol_mandates_approval_judge_gate(db_session):
    """Builder super-design 协议必须含「先 invoke approval_judge 再 request_approval」硬规则。"""
    await seed_admin_user(db_session)
    await seed_builder_project(db_session)

    sup = (await db_session.execute(
        select(Agent).where(Agent.slug == "builder")
    )).scalar_one()

    proto = sup.protocol_md or ""
    assert "approval_judge" in proto, "Builder 协议必须提到 approval_judge"
    assert "force_human" in proto, "Builder 协议必须提到 force_human"
