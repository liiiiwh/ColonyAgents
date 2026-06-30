"""R3-7 · 压缩摘要纯函数 · 从 compression_service 抽 _fallback_summarize + _build_summarize_payload。

进一步瘦 compression_service（1473 LOC 最大文件）。两个函数都是纯（duck-type Message）。
"""
from __future__ import annotations

import json

import pytest


class _FakeMsg:
    def __init__(self, role, content, meta=None, created_at=None):
        self.role = role
        self.content = content
        self.meta = meta or {}
        self.created_at = created_at


def test_fallback_summarize_truncates_long_body():
    from app.domain.compression.summarizer import fallback_summarize
    long = "x" * 1000
    out = fallback_summarize([_FakeMsg("user", long)])
    assert "降级摘要" in out
    assert "…" in out  # 头尾截断标记
    assert len(out) < 800  # 不再是 1000+


def test_fallback_summarize_inlines_meta_hint():
    from app.domain.compression.summarizer import fallback_summarize
    out = fallback_summarize([_FakeMsg("assistant", "做了事", meta={"tool_calls": [1], "artifacts": ["a"]})])
    assert "meta:" in out
    assert "tool_calls" in out and "artifacts" in out


def test_fallback_summarize_skips_empty():
    from app.domain.compression.summarizer import fallback_summarize
    out = fallback_summarize([_FakeMsg("user", ""), _FakeMsg("user", "real")])
    assert "real" in out
    assert out.count("- [") == 1  # 只有 1 行（空消息跳过）


def test_build_payload_shrinks_data_uri_attachment():
    """data URI 图不应原样进 payload（撑爆 LLM）→ 压成简短描述。"""
    from app.domain.compression.summarizer import build_summarize_payload
    big_data_uri = "data:image/png;base64," + "A" * 5000
    out = build_summarize_payload([
        _FakeMsg("user", "看图", meta={"attachments": [
            {"type": "image", "name": "foo.png", "media_type": "image/png", "content": big_data_uri}
        ]})
    ])
    parsed = json.loads(out)
    att = parsed[0]["meta"]["attachments"][0]
    assert "data URI" in att["content_ref"]
    assert "A" * 5000 not in out  # 原始 base64 不在


def test_build_payload_truncates_long_content():
    from app.domain.compression.summarizer import build_summarize_payload
    out = build_summarize_payload([_FakeMsg("assistant", "y" * 3000)])
    parsed = json.loads(out)
    assert "中略" in parsed[0]["content"]
    assert len(parsed[0]["content"]) < 1500


def test_build_payload_keeps_url_attachment_short():
    from app.domain.compression.summarizer import build_summarize_payload
    out = build_summarize_payload([
        _FakeMsg("user", "x", meta={"attachments": [
            {"type": "file", "name": "d.pdf", "content": "https://s3/" + "p" * 500}
        ]})
    ])
    parsed = json.loads(out)
    ref = parsed[0]["meta"]["attachments"][0]["content_ref"]
    assert ref.startswith("https://s3/")
    assert len(ref) <= 200
