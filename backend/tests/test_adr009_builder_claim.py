"""ADR-009 G4 · Builder 多 session 对 mutation 目标的互斥锁（纯决策）。

Builder 是一个 super，可有多个 session。两个 session 不能并发改同一个 worker/super/skill。
decide_claim(existing_claim, requester_session) → grant | reuse | reject。
"""
from __future__ import annotations


def test_grant_when_no_existing_claim():
    from app.domain.builder.work_claim import decide_claim
    d = decide_claim(existing=None, requester_session_id="s1")
    assert d.outcome == "grant"


def test_reuse_when_same_session_holds():
    from app.domain.builder.work_claim import decide_claim
    existing = {"session_id": "s1", "status": "active"}
    d = decide_claim(existing=existing, requester_session_id="s1")
    assert d.outcome == "reuse"


def test_reject_when_other_session_holds_active():
    from app.domain.builder.work_claim import decide_claim
    existing = {"session_id": "s1", "status": "active"}
    d = decide_claim(existing=existing, requester_session_id="s2")
    assert d.outcome == "reject"
    assert "s1" in d.holder_session_id


def test_grant_when_existing_claim_released():
    from app.domain.builder.work_claim import decide_claim
    existing = {"session_id": "s1", "status": "released"}
    d = decide_claim(existing=existing, requester_session_id="s2")
    assert d.outcome == "grant"


def test_grant_when_existing_claim_stale():
    """active 但超过 TTL 视为陈旧（持有 session 崩了），允许抢占。"""
    from app.domain.builder.work_claim import decide_claim
    existing = {"session_id": "s1", "status": "active", "age_seconds": 99999}
    d = decide_claim(existing=existing, requester_session_id="s2", ttl_seconds=3600)
    assert d.outcome == "grant"


def test_claim_key_normalizes_target():
    from app.domain.builder.work_claim import claim_key
    assert claim_key("worker", "xhs_ops") == "worker:xhs_ops"
    assert claim_key("Super", " MySlug ") == "super:myslug"
