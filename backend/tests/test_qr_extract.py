"""ADR-010 R4 fix · _extract_qr_image：从 MCP get_login_qrcode 返回抽二维码图。

xhs-mcp 返回 base64 image block，不是 url —— 之前 card 没图。
"""
from app.services.readiness import _extract_qr_image


def test_base64_image_block_to_data_uri():
    res = [{"type": "text", "text": "请扫码"},
           {"type": "image", "base64": "iVBORw0KGgoAAAANSU" + "A" * 50}]
    out = _extract_qr_image(res)
    assert out.startswith("data:image/png;base64,iVBOR")


def test_https_url():
    assert _extract_qr_image("二维码 https://x/qr.png 请扫") == "https://x/qr.png"


def test_string_base64_fallback():
    s = "[{'type':'image','base64':'" + "Z" * 60 + "'}]"
    assert _extract_qr_image(s).startswith("data:image/png;base64,ZZZ")


def test_none_when_absent():
    assert _extract_qr_image("没有二维码") is None
    assert _extract_qr_image([{"type": "text", "text": "hi"}]) is None
