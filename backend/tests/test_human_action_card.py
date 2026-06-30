"""ADR-010 R4 · 人类残留卡正文构建（纯逻辑）。

按 kind 渲染：human-qr 嵌二维码 markdown 图 / human-secret 要 key / instructions 列步骤。
复用 request_approval 的 markdown message 通道（clawbot 已验证可嵌图）。
"""
from app.domain.human_action import build_human_action_card


def test_qr_card_embeds_image_markdown():
    card = build_human_action_card(
        {"id": "logged_in", "kind": "human-qr"},
        server_name="xhs-mcp",
        qr_image_url="https://x/qr.png",
    )
    assert "xhs-mcp" in card["title"]
    assert "![" in card["body"] and "https://x/qr.png" in card["body"]  # markdown 图
    assert any("已扫码" in o or "完成" in o for o in card["options"])


def test_secret_card_lists_keys_and_says_no_autofill():
    card = build_human_action_card(
        {"id": "secret:XHS_KEY", "kind": "human-secret"},
        server_name="cloud-mcp", secret_keys=["XHS_KEY"],
    )
    assert "XHS_KEY" in card["body"]
    assert "不会代填" in card["body"] or "代填" in card["body"]


def test_instructions_card_numbers_steps():
    card = build_human_action_card(
        {"id": "manual_setup", "kind": "instructions"},
        server_name="weird-mcp", steps=["装 brew", "跑 init"],
    )
    assert "1. 装 brew" in card["body"]
    assert "2. 跑 init" in card["body"]
