"""ADR-008 P4 · WeChat Router 路由决策（纯函数，可独立测）。

一个微信账号服务 N 个 super（MissionApprovalChannel 多对一）。用户发自由消息时，
要决定这条消息进哪个 super 的哪个 session：

  0 候选 → none（回「你还没有可对话的 super」）
  1 候选 → 直达
  N 候选 → 优先级：
     用户回了菜单编号        → 该候选
     有粘性会话且未要求改路由 → 粘同 session（连续对话不重复问）
     LLM 语义匹配命中 slug    → 该候选
     都没有                   → 发编号菜单问用户

实际 DB 查询 / LLM 调用 / 消息注入 / idle-trigger 在 services/wechat_router.py。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Candidate:
    mission_id: str
    slug: str
    name: str
    session_id: str
    description: str = ""


@dataclass
class RouteDecision:
    kind: str  # "none" | "route" | "ask"
    target: Candidate | None = None
    menu_text: str = ""
    reason: str = ""
    candidates: list[Candidate] = field(default_factory=list)


def parse_menu_choice(text: str) -> int | None:
    """用户回复是否一个菜单编号（1-2 位纯数字，可带少量修饰词如「回复编号 3」）。

    8 位 hex request_id / 长文本不应误判。仅当整段文本里只有一个 1-2 位数字、
    且没有大段其它内容时才认定为菜单选择。
    """
    if not text:
        return None
    t = text.strip()
    # 整段就是一个 1-2 位数字（允许前后少量非数字修饰，如「回复编号 3」「选 2」）
    m = re.fullmatch(r"\D{0,6}(\d{1,2})\D{0,2}", t)
    if not m:
        return None
    return int(m.group(1))


def build_menu_text(candidates: list[Candidate]) -> str:
    lines = ["你有多个可对话的 super，这条消息发给哪个？"]
    for i, c in enumerate(candidates, start=1):
        desc = f" — {c.description}" if c.description else ""
        lines.append(f"{i}. {c.name} ({c.slug}){desc}")
    lines.append("回复编号即可（如「1」）。")
    return "\n".join(lines)


def decide_route(
    *,
    candidates: list[Candidate],
    cached_session_id: str | None = None,
    menu_choice: int | None = None,
    llm_pick_slug: str | None = None,
    force_reroute: bool = False,
) -> RouteDecision:
    if not candidates:
        return RouteDecision(kind="none", reason="no_candidate")

    # 1) 用户明确回了菜单编号 → 直接解析（覆盖粘性）
    if menu_choice is not None:
        if 1 <= menu_choice <= len(candidates):
            return RouteDecision(
                kind="route", target=candidates[menu_choice - 1],
                reason="menu_choice", candidates=candidates,
            )
        return RouteDecision(
            kind="ask", menu_text=build_menu_text(candidates),
            reason="menu_invalid", candidates=candidates,
        )

    # 2) 单候选直达
    if len(candidates) == 1:
        return RouteDecision(kind="route", target=candidates[0], reason="single", candidates=candidates)

    # 3) 粘性会话（连续对话粘同 session，除非显式要求改路由）
    if cached_session_id and not force_reroute:
        c = next((c for c in candidates if c.session_id == cached_session_id), None)
        if c is not None:
            return RouteDecision(kind="route", target=c, reason="sticky", candidates=candidates)

    # 4) LLM 语义匹配命中
    if llm_pick_slug:
        c = next((c for c in candidates if c.slug == llm_pick_slug), None)
        if c is not None:
            return RouteDecision(kind="route", target=c, reason="llm_pick", candidates=candidates)

    # 5) 多候选无法确定 → 发菜单
    return RouteDecision(
        kind="ask", menu_text=build_menu_text(candidates),
        reason="ambiguous", candidates=candidates,
    )


# ─────────────────── 粘性路由缓存（纯转换） ───────────────────
# cache 形如 {wechat_user_id: {"sticky": <target_id>, "pending_text": <发菜单时暂存的原文>}}

def sticky_for(cache: dict, uid: str) -> str | None:
    entry = (cache or {}).get(uid) or {}
    return entry.get("sticky") or None


def pending_text_for(cache: dict, uid: str) -> str | None:
    entry = (cache or {}).get(uid) or {}
    return entry.get("pending_text") or None


def stash_for_menu(cache: dict, uid: str, pending_text: str) -> dict:
    """发菜单问用户时，暂存用户原始消息（待用户回编号后再注入）。"""
    new = dict(cache or {})
    entry = dict(new.get(uid) or {})
    entry["pending_text"] = pending_text
    new[uid] = entry
    return new


def commit_route(cache: dict, uid: str, target_id: str) -> dict:
    """成功路由后：记 sticky、清掉 pending_text。"""
    new = dict(cache or {})
    entry = dict(new.get(uid) or {})
    entry["sticky"] = target_id
    entry.pop("pending_text", None)
    new[uid] = entry
    return new
