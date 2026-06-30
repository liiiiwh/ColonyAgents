"""ADR-009 G1 · 改 worker 前的跨 super 影响分析（纯函数）。

worker 平台共享，改契约立即对所有 super 生效。这里基于「每个消费 super 实际用过的 action 集」
判断新契约会不会破坏某个 super —— 只要有一个会破坏就 not safe（硬阻断的依据）。

关键比 check_backward_compat 更严：一个 action 即便进了 deprecated_actions，但若有 super 仍在用，
删掉它 = 破坏该 super → breaking（不能「一边好一边坏」）。
"""
from __future__ import annotations


def test_safe_when_no_consumers():
    from app.domain.builder.spec_validation import analyze_worker_change_impact
    old = {"advertises": [{"action": "publish"}]}
    new = {"advertises": [{"action": "publish_v2"}]}
    res = analyze_worker_change_impact(old_contract=old, new_contract=new, consumers=[])
    assert res["safe"] is True
    assert res["breaking"] == []


def test_safe_when_used_actions_preserved_compatibly():
    from app.domain.builder.spec_validation import analyze_worker_change_impact
    old = {"advertises": [{"action": "publish", "input_schema": {"title": "str"}, "output_schema": {"id": "str"}}]}
    new = {"advertises": [{"action": "publish", "input_schema": {"title": "str", "tag": "str?"}, "output_schema": {"id": "str", "url": "str"}}]}
    consumers = [{"super_slug": "xhs-a", "used_actions": ["publish"]}]
    res = analyze_worker_change_impact(old_contract=old, new_contract=new, consumers=consumers)
    assert res["safe"] is True


def test_breaking_when_used_action_removed():
    from app.domain.builder.spec_validation import analyze_worker_change_impact
    old = {"advertises": [{"action": "publish"}, {"action": "comment"}]}
    new = {"advertises": [{"action": "publish"}]}  # comment 没了
    consumers = [
        {"super_slug": "xhs-a", "used_actions": ["publish"]},        # 不受影响
        {"super_slug": "xhs-b", "used_actions": ["publish", "comment"]},  # 用了 comment → 破坏
    ]
    res = analyze_worker_change_impact(old_contract=old, new_contract=new, consumers=consumers)
    assert res["safe"] is False
    slugs = {b["super_slug"] for b in res["breaking"]}
    assert slugs == {"xhs-b"}
    assert "comment" in res["breaking"][0]["broken_actions"]


def test_deprecated_but_still_used_action_is_still_breaking():
    """即便进了 deprecated_actions，只要还有 super 在用，删掉就是破坏。"""
    from app.domain.builder.spec_validation import analyze_worker_change_impact
    old = {"advertises": [{"action": "publish"}, {"action": "old_post"}]}
    new = {"advertises": [{"action": "publish"}], "deprecated_actions": ["old_post"]}
    consumers = [{"super_slug": "legacy-super", "used_actions": ["old_post"]}]
    res = analyze_worker_change_impact(old_contract=old, new_contract=new, consumers=consumers)
    assert res["safe"] is False
    assert "old_post" in res["breaking"][0]["broken_actions"]


def test_breaking_when_used_action_gets_new_required_input():
    from app.domain.builder.spec_validation import analyze_worker_change_impact
    old = {"advertises": [{"action": "publish", "input_schema": {"title": "str"}}]}
    new = {"advertises": [{"action": "publish", "input_schema": {"title": "str", "author": "str"}}]}
    consumers = [{"super_slug": "xhs-a", "used_actions": ["publish"]}]
    res = analyze_worker_change_impact(old_contract=old, new_contract=new, consumers=consumers)
    assert res["safe"] is False
    assert "publish" in res["breaking"][0]["broken_actions"]


def test_unused_removed_action_does_not_break():
    """删了一个 action，但没有任何 super 用过它 → 安全。"""
    from app.domain.builder.spec_validation import analyze_worker_change_impact
    old = {"advertises": [{"action": "publish"}, {"action": "rare_action"}]}
    new = {"advertises": [{"action": "publish"}]}
    consumers = [{"super_slug": "xhs-a", "used_actions": ["publish"]}]
    res = analyze_worker_change_impact(old_contract=old, new_contract=new, consumers=consumers)
    assert res["safe"] is True
