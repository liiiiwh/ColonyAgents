"""R3-4 · ApprovalResolution · 统一「批准之后」的分叉决策。

decide() 后按 session.scope 分叉：orchestrator→advance / daemon+affirmative→publisher。
把「该触发哪个 hook」抽成纯函数 route_post_decision，可独立测；实际 create_task 仍在 decide。
"""
from __future__ import annotations

import pytest


def test_orchestrator_scope_routes_to_advance():
    from app.domain.approval.resolution import route_post_decision, PostDecisionAction
    assert route_post_decision(scope="orchestrator", option="任意") == PostDecisionAction.ADVANCE_ORCHESTRATOR


def test_daemon_affirmative_routes_to_trigger_tick():
    """ADR-008 D2 · daemon 审批回复统一触发 tick（不再走 affirmative-only fast-path）。"""
    from app.domain.approval.resolution import route_post_decision, PostDecisionAction
    assert route_post_decision(scope="daemon", option="同意发布") == PostDecisionAction.TRIGGER_TICK


def test_daemon_negative_also_routes_to_trigger_tick():
    """ADR-008 D2 · daemon + 拒绝语义也触发 tick（super 读 [approval_response] 自行决定怎么继续）。"""
    from app.domain.approval.resolution import route_post_decision, PostDecisionAction
    assert route_post_decision(scope="daemon", option="拒绝") == PostDecisionAction.TRIGGER_TICK


def test_unknown_scope_routes_to_none():
    from app.domain.approval.resolution import route_post_decision, PostDecisionAction
    assert route_post_decision(scope="mission_chat", option="同意") == PostDecisionAction.NONE


def test_affirmative_detection_matches_legacy_keywords():
    """肯定语义判定与 legacy _option_is_affirmative 一致。"""
    from app.domain.approval.resolution import is_affirmative
    assert is_affirmative("同意") is True
    assert is_affirmative("通过") is True
    assert is_affirmative("确认发布") is True
    assert is_affirmative("拒绝") is False
    assert is_affirmative("再改改") is False
