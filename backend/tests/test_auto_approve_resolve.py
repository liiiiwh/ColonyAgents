"""resolve_auto_approve 纯函数 · 决定 request_approval 是否自动通过。

规则（优先级从高到低）：
1. must_human=True → 永远等真人（无视任何 auto 信号）。super 用它兑现"到 X 再问我"。
2. ctx 强制 auto（force_auto_approve）→ 自动通过。用于系统级后台会话（如平台 Worker 健康自检），
   没有真人盯 SSE 卡片，必须自动推进，否则审批卡永远挂起。
3. 否则看项目 auto_approve 设置。
"""
from __future__ import annotations

from app.domain.auto_approve import resolve_auto_approve


def test_force_human_always_blocks_even_with_ctx_auto():
    assert resolve_auto_approve(must_human=True, ctx_force_auto=True, project_auto_approve=True) is False


def test_force_human_blocks_with_project_auto():
    assert resolve_auto_approve(must_human=True, ctx_force_auto=False, project_auto_approve=True) is False


def test_ctx_force_auto_approves_even_if_project_manual():
    """系统级自检会话：项目 manual，但 ctx 强制 auto → 自动通过。"""
    assert resolve_auto_approve(must_human=False, ctx_force_auto=True, project_auto_approve=False) is True


def test_falls_back_to_project_auto_true():
    assert resolve_auto_approve(must_human=False, ctx_force_auto=False, project_auto_approve=True) is True


def test_falls_back_to_project_auto_false():
    assert resolve_auto_approve(must_human=False, ctx_force_auto=False, project_auto_approve=False) is False


# ── ADR-028 D1 · must_human=True 是人工门硬停点：永远 False，无视任何 auto 信号 ──
# approval_judge 判 must_human=True → super 传 must_human=True → 此函数永远 False →
# 即使 mission.auto_approve=True / ctx 强制 auto 也硬停等真人（落卡 + cancel tick 由 D4 接线）。


def test_d1_force_human_blocks_all_auto_combinations():
    """must_human=True 凌驾 ctx_force_auto 与 project_auto_approve 的所有组合。"""
    for ctx_auto in (True, False):
        for proj_auto in (True, False):
            assert (
                resolve_auto_approve(
                    must_human=True,
                    ctx_force_auto=ctx_auto,
                    project_auto_approve=proj_auto,
                )
                is False
            ), f"must_human=True 必须硬停 (ctx_auto={ctx_auto}, proj_auto={proj_auto})"


def test_d1_force_human_overrides_system_session_force_auto():
    """系统级后台会话（ctx_force_auto）也压不过 force_human（人审 > 系统 auto）。"""
    assert resolve_auto_approve(
        must_human=True, ctx_force_auto=True, project_auto_approve=False
    ) is False
