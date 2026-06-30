"""R2-1 第 1 段 · WorkerInvocation precheck 纯函数 extraction。

invoke_worker 入口的前置校验（V17 嵌套 / V37 反问 / 必需 ctx 字段）从 374-LOC 巨函数里抽出来。
纯函数 → 单元可测，不需 LangChain / DB mock。
"""
from __future__ import annotations

import pytest


def test_precheck_blocks_nesting_overflow():
    """V17: invoke_worker 嵌套 >= max_nesting → 拒绝。"""
    from app.domain.dispatch.precheck import precheck_invocation

    res = precheck_invocation(
        call_stack=["w1", "w2", "w3"],
        clarification_round=0,
        super_id="super-uuid",
        max_nesting=3,
        max_clarification_rounds=5,
    )
    assert res.ok is False
    assert "嵌套深度超" in res.error_msg
    assert "V17" in res.error_msg


def test_precheck_blocks_clarification_overflow():
    """V37: clarification 轮数超 → 拒绝。"""
    from app.domain.dispatch.precheck import precheck_invocation

    res = precheck_invocation(
        call_stack=[],
        clarification_round=5,
        super_id="super-uuid",
        max_nesting=3,
        max_clarification_rounds=5,
    )
    assert res.ok is False
    assert "clarification" in res.error_msg.lower()
    assert "V37" in res.error_msg


def test_precheck_requires_super_id():
    """ctx.extra.agent_id 缺失 → 拒绝。"""
    from app.domain.dispatch.precheck import precheck_invocation

    res = precheck_invocation(
        call_stack=[],
        clarification_round=0,
        super_id=None,
        max_nesting=3,
        max_clarification_rounds=5,
    )
    assert res.ok is False
    assert "agent_id" in res.error_msg


def test_precheck_passes_with_valid_input():
    from app.domain.dispatch.precheck import precheck_invocation

    res = precheck_invocation(
        call_stack=["w1"],
        clarification_round=1,
        super_id="super-uuid",
        max_nesting=3,
        max_clarification_rounds=5,
    )
    assert res.ok is True
    assert res.error_msg is None


def test_precheck_envelope_shape_failed_status():
    """失败时返回的 envelope 兼容现有 invoke_worker 调用方 (status='failed' + ok=False)。"""
    from app.domain.dispatch.precheck import precheck_invocation

    res = precheck_invocation(
        call_stack=[],
        clarification_round=99,
        super_id="x",
        max_nesting=3,
        max_clarification_rounds=5,
    )
    env = res.to_envelope()
    assert env["ok"] is False
    assert env["status"] == "failed"
    assert "error_msg" in env
