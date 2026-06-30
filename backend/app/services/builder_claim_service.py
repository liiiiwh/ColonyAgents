"""ADR-009 G4 · Builder 多 session 互斥锁服务（DB 行锁 + 纯决策）。

acquire_claim：当前 session 想改某 worker/super/skill 前调。被其它 session 持有 → 拒绝。
release_claim：mutation 终态（成功/失败）后释放。

纯判定在 app/domain/builder/work_claim.py（已单测）。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.builder.work_claim import claim_key, decide_claim
from app.models.builder_governance import BuilderWorkClaim

logger = logging.getLogger(__name__)


async def acquire_claim(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    session_id,
    mission_id=None,
    ttl_seconds: int = 1800,
) -> dict:
    """尝试为 session 获取 target 的独占锁。

    返回 {ok, outcome: grant|reuse|reject, holder_session_id?, message}。
    """
    key = claim_key(target_type, target_id)
    row = (await db.execute(
        select(BuilderWorkClaim).where(BuilderWorkClaim.key == key)
    )).scalar_one_or_none()

    existing = None
    if row is not None:
        age = None
        if row.claimed_at is not None:
            now = datetime.now(UTC)
            claimed = row.claimed_at if row.claimed_at.tzinfo else row.claimed_at.replace(tzinfo=UTC)
            age = (now - claimed).total_seconds()
        existing = {"session_id": str(row.session_id), "status": row.status, "age_seconds": age}

    decision = decide_claim(
        existing=existing, requester_session_id=str(session_id), ttl_seconds=ttl_seconds,
    )

    if decision.outcome == "reject":
        return {
            "ok": False,
            "outcome": "reject",
            "holder_session_id": decision.holder_session_id,
            "message": (
                f"另一个 Builder session（{decision.holder_session_id[:8]}）正在处理 {key}，"
                "请切到那个 session 继续，或等它完成/释放后再来。避免两个 session 改坏同一目标。"
            ),
        }

    if decision.outcome == "reuse":
        return {"ok": True, "outcome": "reuse", "message": f"本 session 已持有 {key}。"}

    # grant：新建或抢占现有行
    now = datetime.now(UTC)
    if row is None:
        db.add(BuilderWorkClaim(
            key=key, target_type=target_type.strip().lower(), target_id=target_id,
            session_id=session_id, mission_id=mission_id, status="active", claimed_at=now,
        ))
    else:
        row.session_id = session_id
        row.mission_id = mission_id
        row.status = "active"
        row.claimed_at = now
        row.released_at = None
    await db.commit()
    return {"ok": True, "outcome": "grant", "message": f"已获取 {key} 的处理权。"}


async def release_claim(
    db: AsyncSession, *, target_type: str, target_id: str, session_id=None
) -> dict:
    """释放锁（mutation 终态后调）。只释放本 session 持有的（除非 session_id=None 强制）。"""
    key = claim_key(target_type, target_id)
    row = (await db.execute(
        select(BuilderWorkClaim).where(BuilderWorkClaim.key == key)
    )).scalar_one_or_none()
    if row is None or row.status != "active":
        return {"ok": True, "released": False}
    if session_id is not None and str(row.session_id) != str(session_id):
        return {"ok": False, "released": False, "message": "锁不属于本 session，未释放"}
    row.status = "released"
    row.released_at = datetime.now(UTC)
    await db.commit()
    return {"ok": True, "released": True}
