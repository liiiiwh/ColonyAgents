"""ADR-008 P4 · WeChat Router 路由决策（纯函数）。

一个微信账号服务 N 个 super（MissionApprovalChannel 多对一）。用户发自由消息时，
router 决定路由到哪个 super session：0空 / 1直达 / N→LLM语义→不确定发菜单 / 用户回编号 / 粘性会话。
"""
from __future__ import annotations


def _c(slug, sid, name=None, desc=""):
    from app.domain.wechat.router_policy import Candidate
    return Candidate(mission_id="p-" + slug, slug=slug, name=name or slug, session_id=sid, description=desc)


def test_no_candidate_returns_none():
    from app.domain.wechat.router_policy import decide_route
    d = decide_route(candidates=[])
    assert d.kind == "none"


def test_single_candidate_routes_direct():
    from app.domain.wechat.router_policy import decide_route
    cands = [_c("xhs", "s1")]
    d = decide_route(candidates=cands)
    assert d.kind == "route"
    assert d.target.session_id == "s1"
    assert d.reason == "single"


def test_multiple_no_signal_asks_menu():
    from app.domain.wechat.router_policy import decide_route
    cands = [_c("xhs", "s1", "小红书运营"), _c("promo", "s2", "colony推广")]
    d = decide_route(candidates=cands)
    assert d.kind == "ask"
    assert "1." in d.menu_text and "2." in d.menu_text
    assert "小红书运营" in d.menu_text and "colony推广" in d.menu_text


def test_menu_choice_resolves_to_candidate():
    from app.domain.wechat.router_policy import decide_route
    cands = [_c("xhs", "s1"), _c("promo", "s2")]
    d = decide_route(candidates=cands, menu_choice=2)
    assert d.kind == "route"
    assert d.target.slug == "promo"
    assert d.reason == "menu_choice"


def test_menu_choice_out_of_range_reasks():
    from app.domain.wechat.router_policy import decide_route
    cands = [_c("xhs", "s1"), _c("promo", "s2")]
    d = decide_route(candidates=cands, menu_choice=9)
    assert d.kind == "ask"


def test_sticky_cached_session_wins_when_multiple():
    from app.domain.wechat.router_policy import decide_route
    cands = [_c("xhs", "s1"), _c("promo", "s2")]
    d = decide_route(candidates=cands, cached_session_id="s2")
    assert d.kind == "route"
    assert d.target.session_id == "s2"
    assert d.reason == "sticky"


def test_force_reroute_ignores_sticky_and_asks():
    from app.domain.wechat.router_policy import decide_route
    cands = [_c("xhs", "s1"), _c("promo", "s2")]
    d = decide_route(candidates=cands, cached_session_id="s2", force_reroute=True)
    assert d.kind == "ask"


def test_llm_pick_routes_when_ambiguous():
    from app.domain.wechat.router_policy import decide_route
    cands = [_c("xhs", "s1"), _c("promo", "s2")]
    d = decide_route(candidates=cands, llm_pick_slug="promo")
    assert d.kind == "route"
    assert d.target.slug == "promo"
    assert d.reason == "llm_pick"


def test_menu_choice_overrides_sticky():
    from app.domain.wechat.router_policy import decide_route
    cands = [_c("xhs", "s1"), _c("promo", "s2")]
    d = decide_route(candidates=cands, cached_session_id="s1", menu_choice=2)
    assert d.kind == "route"
    assert d.target.slug == "promo"


def test_parse_menu_choice_plain_number():
    from app.domain.wechat.router_policy import parse_menu_choice
    assert parse_menu_choice("2") == 2
    assert parse_menu_choice(" 1 ") == 1
    assert parse_menu_choice("回复编号 3") == 3


def test_parse_menu_choice_rejects_non_menu_text():
    from app.domain.wechat.router_policy import parse_menu_choice
    assert parse_menu_choice("帮我发一篇关于咖啡的笔记") is None
    assert parse_menu_choice("") is None
    # 8 位 hex request_id 不应误判成菜单编号
    assert parse_menu_choice("ab12cd34") is None


def test_cache_stash_and_commit_roundtrip():
    from app.domain.wechat.router_policy import (
        stash_for_menu, commit_route, sticky_for, pending_text_for,
    )
    cache: dict = {}
    # 发菜单时暂存原文
    cache = stash_for_menu(cache, "u1", "发一篇咖啡笔记")
    assert pending_text_for(cache, "u1") == "发一篇咖啡笔记"
    assert sticky_for(cache, "u1") is None
    # 用户回编号 → 路由成功，记 sticky 清 pending
    cache = commit_route(cache, "u1", "proj-2")
    assert sticky_for(cache, "u1") == "proj-2"
    assert pending_text_for(cache, "u1") is None


def test_cache_isolated_per_user():
    from app.domain.wechat.router_policy import commit_route, sticky_for
    cache = commit_route({}, "u1", "proj-1")
    cache = commit_route(cache, "u2", "proj-2")
    assert sticky_for(cache, "u1") == "proj-1"
    assert sticky_for(cache, "u2") == "proj-2"
