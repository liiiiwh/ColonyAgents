"""R4-4 · super_chat intake · 把 POST /chat 内联的领域规则下沉。

两块抽出：
- build_user_message_content（纯）：用户文本 + attachments → markdown（让 super 看到）
- auto_decide_oldest_pending（domain/approval）：未审批时 chat 当审批意见
"""
from __future__ import annotations

import pytest


class _FakeAtt:
    def __init__(self, kind, name, url):
        self.kind = kind
        self.name = name
        self.url = url


def test_content_without_attachments_unchanged():
    from app.domain.super_chat.intake import build_user_message_content
    assert build_user_message_content("你好", []) == "你好"


def test_content_with_image_attachment_markdown():
    from app.domain.super_chat.intake import build_user_message_content
    out = build_user_message_content("看图", [_FakeAtt("image", "foo.png", "https://s3/foo.png")])
    assert "看图" in out
    assert "![foo.png](https://s3/foo.png)" in out


def test_content_with_file_attachment_markdown():
    from app.domain.super_chat.intake import build_user_message_content
    out = build_user_message_content("看文件", [_FakeAtt("file", "d.pdf", "https://s3/d.pdf")])
    assert "[📎 d.pdf](https://s3/d.pdf)" in out


def test_content_multiple_attachments():
    from app.domain.super_chat.intake import build_user_message_content
    out = build_user_message_content("混合", [
        _FakeAtt("image", "a.png", "u1"),
        _FakeAtt("file", "b.pdf", "u2"),
    ])
    assert "![a.png](u1)" in out
    assert "[📎 b.pdf](u2)" in out


def test_auto_decide_helper_exists_in_approval_domain():
    """auto-decide 领域规则归位 approval/resolution（不再裸在 API handler）。"""
    from app.domain.approval.resolution import build_auto_decide_option
    # option = 用户原文截断 500
    assert build_auto_decide_option("同意发布，但把时间改成晚上") == "同意发布，但把时间改成晚上"
    long = "x" * 800
    assert build_auto_decide_option(long) == "x" * 500
