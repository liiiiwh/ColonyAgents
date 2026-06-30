"""ADR-008 P3 · 审批 WeChat 消息构造（纯函数）。

把审批消息体 + 平台深链的拼装抽成纯函数，可独立测；实际发送仍在
pending_approval_service._dispatch_to_wechat。

两条审核路并存：
1. 微信回纯文本：`{request_id} <选项>`
2. 点平台深链：`{frontend_base}/mission/{slug}?session={sid}` → ApprovalCard 审核/提意见
"""
from __future__ import annotations

from collections.abc import Sequence


def build_mission_deep_link(
    *, frontend_base: str, slug: str, session_id: str | None
) -> str:
    """构造 mission 工作台深链。frontend_base 为空则返回空串（无前端配置时退化）。"""
    base = (frontend_base or "").strip().rstrip("/")
    if not base or not slug:
        return ""
    url = f"{base}/mission/{slug}"
    if session_id:
        url += f"?session={session_id}"
    return url


def build_approval_message(
    *,
    request_id: str,
    title: str,
    message: str,
    options: Sequence[str],
    mission_url: str = "",
) -> str:
    """审批 WeChat 消息体。mission_url 非空时追加平台深链行。"""
    options_str = " / ".join(options) if options else "（无候选）"
    lines = [
        f"📋 待审批 [{request_id}]",
        f"标题：{title}",
        "",
        message,
        "",
        f"选项：{options_str}",
        "",
        f"在微信回复格式：{request_id} <选项>",
    ]
    if mission_url:
        lines.append(f"或点此进平台审核/提意见：{mission_url}")
    else:
        lines.append("也可在 observe 页面点击决定。")
    return "\n".join(lines)
