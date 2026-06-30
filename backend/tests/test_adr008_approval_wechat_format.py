"""ADR-008 P3 · 审批 WeChat 消息带平台深链（纯函数）。

审批消息追加 {frontend_base}/mission/{slug}?session={sid}，用户点进平台审核/提意见；
微信回纯文本仍兼容（两条路并存）。
"""
from __future__ import annotations


def test_mission_deep_link_builds_with_session():
    from app.domain.approval.wechat_format import build_mission_deep_link
    url = build_mission_deep_link(
        frontend_base="https://colony.example.com",
        slug="xhs-ops",
        session_id="sess-123",
    )
    assert url == "https://colony.example.com/mission/xhs-ops?session=sess-123"


def test_mission_deep_link_without_session():
    from app.domain.approval.wechat_format import build_mission_deep_link
    url = build_mission_deep_link(
        frontend_base="https://colony.example.com",
        slug="xhs-ops",
        session_id=None,
    )
    assert url == "https://colony.example.com/mission/xhs-ops"


def test_mission_deep_link_empty_base_returns_empty():
    from app.domain.approval.wechat_format import build_mission_deep_link
    assert build_mission_deep_link(frontend_base="", slug="x", session_id="s") == ""


def test_approval_message_includes_deep_link():
    from app.domain.approval.wechat_format import build_approval_message
    body = build_approval_message(
        request_id="ab12cd",
        title="发布确认",
        message="确认发布这条小红书？",
        options=["通过", "驳回"],
        mission_url="https://colony.example.com/mission/xhs-ops?session=s1",
    )
    assert "ab12cd" in body
    assert "发布确认" in body
    assert "通过 / 驳回" in body
    # 平台深链在
    assert "https://colony.example.com/mission/xhs-ops?session=s1" in body
    # 微信纯文本回复格式仍在（两条路并存）
    assert "ab12cd <选项>" in body or "ab12cd <" in body


def test_approval_message_without_url_omits_link_line():
    from app.domain.approval.wechat_format import build_approval_message
    body = build_approval_message(
        request_id="x1",
        title="t",
        message="m",
        options=["ok"],
        mission_url="",
    )
    assert "http" not in body
    assert "x1" in body
