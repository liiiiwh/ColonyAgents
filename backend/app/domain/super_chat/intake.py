"""R4-4 · super_chat intake · POST /chat 领域规则下沉。

build_user_message_content：用户文本 + attachments → 给 super 看的 markdown（纯函数）。
（完整 6 步编排可后续整体下沉；本期先把可独立测的纯逻辑 + auto-decide 规则归位。）
"""
from __future__ import annotations

from typing import Any


def build_user_message_content(content: str, attachments: list[Any] | None) -> str:
    """拼 content：用户文本 + attachments markdown 链接（image 用 ![]()，其它用 [📎 ]()）。"""
    if not attachments:
        return content
    att_lines: list[str] = []
    for a in attachments:
        kind = getattr(a, "kind", None)
        name = getattr(a, "name", "")
        url = getattr(a, "url", "")
        if kind == "image":
            att_lines.append(f"![{name}]({url})")
        else:
            att_lines.append(f"[📎 {name}]({url})")
    if not att_lines:
        return content
    return (content + "\n\n" + "\n".join(att_lines)).strip()
