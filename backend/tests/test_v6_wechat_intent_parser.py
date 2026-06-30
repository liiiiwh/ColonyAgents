"""R3-5 · wechat intent 纯核心 · 微信审批回信解析（风控关键路径）。

free text → {intent, request_id, option} 的判定从 LLM IO / DB 查询里抽出，纯函数边界可测。
"""
from __future__ import annotations

import pytest


class _FakePending:
    def __init__(self, request_id, options):
        self.request_id = request_id
        self.options = options


# ── parse_json_loose ──
def test_parse_json_loose_plain():
    from app.domain.wechat.intent_parser import parse_json_loose
    assert parse_json_loose('{"intent": "decide_approval", "option": "通过"}')["option"] == "通过"


def test_parse_json_loose_code_fence():
    from app.domain.wechat.intent_parser import parse_json_loose
    out = parse_json_loose('```json\n{"intent": "unclear"}\n```')
    assert out["intent"] == "unclear"


def test_parse_json_loose_with_prose_around():
    from app.domain.wechat.intent_parser import parse_json_loose
    out = parse_json_loose('好的，我的判断是 {"intent": "decide_approval", "option": "驳回"} 这样')
    assert out["option"] == "驳回"


# ── fallback heuristic (风控敏感) ──
def test_fallback_exact_option_match_single_pending():
    from app.domain.wechat.intent_parser import fallback_classify
    p = _FakePending("abc12345", ["通过", "驳回"])
    out = fallback_classify("通过", [p], "llm down")
    assert out["intent"] == "decide_approval"
    assert out["option"] == "通过"
    assert out["request_id"] == "abc12345"


def test_fallback_request_id_shortcode_locks_pending():
    from app.domain.wechat.intent_parser import fallback_classify
    p1 = _FakePending("aaaa1111", ["通过", "驳回"])
    p2 = _FakePending("bbbb2222", ["发布", "取消"])
    out = fallback_classify("bbbb2222 发布", [p1, p2], "")
    assert out["request_id"] == "bbbb2222"
    assert out["option"] == "发布"


def test_fallback_positive_keyword_single_pending():
    """单 pending + 「同意」正向关键词 → 选肯定 option。"""
    from app.domain.wechat.intent_parser import fallback_classify
    p = _FakePending("abc12345", ["✓ 通过", "✗ 驳回"])
    out = fallback_classify("同意", [p], "")
    assert out["intent"] == "decide_approval"
    assert "通过" in out["option"]


def test_fallback_confirm_matches_option_head_single_pending():
    """用户回「确认」，选项是「确认，按此配置创建」→ 应命中该选项（用户输入是选项的头部）。

    回归：微信侧回「确认」报「未识别 (Expecting value...)」。
    """
    from app.domain.wechat.intent_parser import fallback_classify
    p = _FakePending("55ef6b22", ["确认，按此配置创建", "调整汇报时间", "返回重新填写 goal_spec"])
    out = fallback_classify("确认", [p], "Expecting value: line 1 column 1 (char 0)")
    assert out["intent"] == "decide_approval"
    assert out["option"] == "确认，按此配置创建"
    assert out["request_id"] == "55ef6b22"


def test_fallback_unclear_does_not_leak_raw_json_err():
    """unclear 文案不应把 LLM 的 JSON 解析错误原文 (Expecting value…) 透给用户。"""
    from app.domain.wechat.intent_parser import fallback_classify
    p1 = _FakePending("aaaa1111", ["通过", "驳回"])
    p2 = _FakePending("bbbb2222", ["发布", "取消"])
    out = fallback_classify("嗯嗯", [p1, p2], "Expecting value: line 1 column 1 (char 0)")
    assert out["intent"] == "unclear"
    assert "Expecting value" not in out["reply_text"]


def test_fallback_ambiguous_returns_unclear():
    """多 pending 都没精确命中 → unclear（不能瞎批，风控）。"""
    from app.domain.wechat.intent_parser import fallback_classify
    p1 = _FakePending("aaaa1111", ["通过", "驳回"])
    p2 = _FakePending("bbbb2222", ["发布", "取消"])
    out = fallback_classify("嗯", [p1, p2], "")
    assert out["intent"] == "unclear"
