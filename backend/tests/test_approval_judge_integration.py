"""ADR-028 D1 · 端到端硬门链路（确定性，不跑 LLM）。

链路：super → invoke approval_judge → must_human=True → request_approval(force_human=True)
→ resolve_auto_approve 返回 False → 即使 mission.auto_approve=True 也硬停。

approval_judge 的判定本身是 LLM 行为（不在此确定性验证），但「判定结果如何驱动硬门」是
纯逻辑，可端到端断言：把 approval_judge 的输出 must_human 映射到 force_human，再过
resolve_auto_approve，确认硬停不被 auto_approve 翻转。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.init_db import seed_admin_user, seed_builder_project
from app.domain.auto_approve import resolve_auto_approve
from app.models.agent import Agent


def _gate(*, judge_verdict_must_human: bool, project_auto_approve: bool) -> bool:
    """ADR-028 D1（修订）· request_approval 服务端门控接线：approval_judge.must_human 直接进
    resolve_auto_approve（不再经 super 传 force_human）。"""
    return resolve_auto_approve(
        must_human=bool(judge_verdict_must_human),
        ctx_force_auto=False,
        project_auto_approve=project_auto_approve,
    )


def test_must_human_true_hard_stops_even_with_auto_approve():
    """approval_judge 判 must_human=True + mission.auto_approve=True → 仍硬停（auto=False）。"""
    assert _gate(judge_verdict_must_human=True, project_auto_approve=True) is False


def test_must_human_false_with_auto_approve_passes():
    """approval_judge 判 routine(must_human=False) + auto_approve=True → 自动通过。"""
    assert _gate(judge_verdict_must_human=False, project_auto_approve=True) is True


def test_must_human_false_without_auto_approve_still_human_reviews():
    """routine 但项目非 auto → 走人审卡（auto=False，但非硬停，可 resume）。"""
    assert _gate(judge_verdict_must_human=False, project_auto_approve=False) is False


@pytest.mark.asyncio
async def test_seeded_approval_judge_is_dispatchable_by_super(db_session):
    """seed 后 approval_judge 可被 super 按 capability 反查 dispatch（capability + contract 就位）。"""
    await seed_admin_user(db_session)
    await seed_builder_project(db_session)

    judge = (await db_session.execute(
        select(Agent).where(Agent.capability == "approval_judge", Agent.kind == "worker")
    )).scalar_one()

    # super 调 invoke_worker('capability:approval_judge', 'judge', ...) 的两个前置：
    # ① 按 capability 能反查到 worker；② 它 advertise 了 'judge' action。
    assert judge.capability == "approval_judge"
    contract = (judge.extra_config or {}).get("capability_contract") or {}
    actions = {a.get("action") for a in (contract.get("advertises") or [])}
    assert "judge" in actions
