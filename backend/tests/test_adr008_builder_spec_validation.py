"""ADR-008 P5 · Builder 工厂硬门校验（纯函数）。

fail-fast：capability_contract 结构校 + 缺 skill 报错（不静默跳过）+ 升级自动 backward_compat。
"""
from __future__ import annotations


# ── capability_contract 结构校验 ──────────────────────────────

def test_valid_contract_has_no_violations():
    from app.domain.builder.spec_validation import validate_capability_contract
    contract = {
        "capability": "xhs_ops",
        "version": "1.0.0",
        "advertises": [
            {"action": "publish_note", "side_effects": ["external_write"], "requires_approval": True},
        ],
    }
    assert validate_capability_contract(contract) == []


def test_contract_missing_advertises_is_violation():
    from app.domain.builder.spec_validation import validate_capability_contract
    v = validate_capability_contract({"capability": "x", "version": "1.0.0"})
    assert v  # 非空
    assert any("advertises" in s for s in v)


def test_contract_action_missing_required_fields():
    from app.domain.builder.spec_validation import validate_capability_contract
    v = validate_capability_contract({
        "advertises": [
            {"action": "do_it"},  # 缺 side_effects + requires_approval
        ],
    })
    assert any("side_effects" in s for s in v)
    assert any("requires_approval" in s for s in v)


def test_contract_action_blank_name_is_violation():
    from app.domain.builder.spec_validation import validate_capability_contract
    v = validate_capability_contract({
        "advertises": [
            {"action": "", "side_effects": [], "requires_approval": False},
        ],
    })
    assert any("action" in s for s in v)


def test_contract_side_effects_must_be_list():
    from app.domain.builder.spec_validation import validate_capability_contract
    v = validate_capability_contract({
        "advertises": [
            {"action": "a", "side_effects": "external_write", "requires_approval": True},
        ],
    })
    assert any("side_effects" in s for s in v)


def test_contract_requires_approval_must_be_bool():
    from app.domain.builder.spec_validation import validate_capability_contract
    v = validate_capability_contract({
        "advertises": [
            {"action": "a", "side_effects": [], "requires_approval": "yes"},
        ],
    })
    assert any("requires_approval" in s for s in v)


# ── 缺 skill 检测 ─────────────────────────────────────────────

def test_missing_skills_detects_gap():
    from app.domain.builder.spec_validation import missing_skills
    miss = missing_skills(requested={"invoke_worker", "ghost_skill"}, found_slugs={"invoke_worker"})
    assert miss == ["ghost_skill"]


def test_missing_skills_empty_when_all_present():
    from app.domain.builder.spec_validation import missing_skills
    assert missing_skills(requested={"a", "b"}, found_slugs={"a", "b", "c"}) == []


# ── backward_compat 纯比对 ────────────────────────────────────

def test_backward_compat_ok_when_action_preserved():
    from app.domain.builder.spec_validation import check_backward_compat
    old = {"advertises": [{"action": "publish", "input_schema": {"title": "str"}, "output_schema": {"id": "str"}}]}
    new = {"advertises": [{"action": "publish", "input_schema": {"title": "str", "tag": "str?"}, "output_schema": {"id": "str", "url": "str"}}]}
    res = check_backward_compat(old, new)
    assert res["compatible"] is True
    assert res["violations"] == []


def test_backward_compat_breaks_on_removed_action():
    from app.domain.builder.spec_validation import check_backward_compat
    old = {"advertises": [{"action": "publish"}]}
    new = {"advertises": [{"action": "publish_v2"}]}
    res = check_backward_compat(old, new)
    assert res["compatible"] is False
    assert any("publish" in v for v in res["violations"])


def test_backward_compat_deprecated_action_is_warning_not_violation():
    from app.domain.builder.spec_validation import check_backward_compat
    old = {"advertises": [{"action": "publish"}]}
    new = {"advertises": [{"action": "publish_v2"}], "deprecated_actions": ["publish"]}
    res = check_backward_compat(old, new)
    assert res["compatible"] is True
    assert res["warnings"]


def test_backward_compat_breaks_on_new_required_input():
    from app.domain.builder.spec_validation import check_backward_compat
    old = {"advertises": [{"action": "publish", "input_schema": {"title": "str"}}]}
    new = {"advertises": [{"action": "publish", "input_schema": {"title": "str", "author": "str"}}]}
    res = check_backward_compat(old, new)
    assert res["compatible"] is False
    assert any("author" in v for v in res["violations"])
