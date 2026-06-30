"""R2-1 · WorkerInvocation envelope parser · 从 worker LLM 输出抽 return_result 结果。

worker 协议规定：执行完一个 action 必须调 `return_result` tool 把结构化结果还给 super。
LangChain 的输出 messages 列表中找到这条 ToolMessage 即为 envelope。

纯函数 unit-testable，不依赖 LangChain（只 duck-type 它的接口）。
"""
from __future__ import annotations

import json
from typing import Iterable


def extract_return_result_envelope(msgs: Iterable) -> dict | None:
    """扫 worker 输出消息（倒序，取最新），找 return_result tool 的 ToolMessage content。

    匹配条件：
    - msg.type == 'tool' (或 role == 'tool'，duck-type)
    - msg.content 是 JSON 且包含 status ∈ {'completed', 'needs_clarification'}

    其它 tool message（如 fetch_data 返回 {'status': 'ok'}）会被 skip，因为它们不是
    return_result envelope shape。malformed JSON 也 skip。
    """
    for m in reversed(list(msgs)):
        role = getattr(m, "type", None) or getattr(m, "role", None)
        if role != "tool":
            continue
        content = getattr(m, "content", "") or ""
        if not isinstance(content, str):
            continue
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("status") in (
            "completed", "needs_clarification"
        ):
            return parsed
    return None
