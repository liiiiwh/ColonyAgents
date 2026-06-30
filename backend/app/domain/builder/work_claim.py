"""ADR-009 G4 · Builder 多 session 互斥锁（纯决策）。

Builder 是一个 super，可同时有多个 session（用户开多个「改 X」对话 + escalation 落 origin session）。
两个 session 并发改同一 worker/super/skill 会互相覆盖。decide_claim 给出纯判定：

  grant  —— 无人持有 / 已释放 / 陈旧（持有 session 崩了，超 TTL）→ 当前 session 获取
  reuse  —— 本 session 已持有 → 幂等复用
  reject —— 其它 session 正持有且未过期 → 拒绝（告知去那个 session 或等它完成）

实际 DB 行锁 + 读写在 services/builder_claim_service.py。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClaimDecision:
    outcome: str  # "grant" | "reuse" | "reject"
    holder_session_id: str = ""
    reason: str = ""


def claim_key(target_type: str, target_id: str) -> str:
    """规范化锁键：worker:<cap> / super:<slug> / skill:<slug>。"""
    return f"{(target_type or '').strip().lower()}:{(target_id or '').strip().lower()}"


def decide_claim(
    *,
    existing: dict | None,
    requester_session_id: str,
    ttl_seconds: int = 1800,
) -> ClaimDecision:
    """existing: 当前锁行（{session_id, status, age_seconds?}）或 None。"""
    if existing is None:
        return ClaimDecision(outcome="grant", reason="no_existing")
    status = existing.get("status")
    holder = str(existing.get("session_id") or "")
    if status != "active":
        return ClaimDecision(outcome="grant", reason="prev_released")
    # active：超 TTL 视为陈旧（持有方崩溃/卡死），允许抢占
    age = existing.get("age_seconds")
    if age is not None and age > ttl_seconds:
        return ClaimDecision(outcome="grant", reason="stale_takeover", holder_session_id=holder)
    if holder == str(requester_session_id):
        return ClaimDecision(outcome="reuse", holder_session_id=holder, reason="same_session")
    return ClaimDecision(outcome="reject", holder_session_id=holder, reason="held_by_other")
