"""ADR-009 · Builder 治理表：多 session 互斥锁 + per-session 工作记录。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BuilderWorkClaim(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """G4 · Builder session 对某 mutation 目标（worker/super/skill）的独占锁。

    key = claim_key(target_type, target_id)，唯一。防两个 Builder session 并发改同一目标。
    """

    __tablename__ = "builder_work_claims"

    key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)  # worker / super / skill
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # ADR-018 mission-only · 去 sessions FK + nullable（保留列作历史审计；sessions 表退役）
    session_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active / released
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BuilderWorkLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """G5 · Builder 每 session 的结构化变更审计：建/升了什么、影响了哪些 super、结果。"""

    __tablename__ = "builder_work_logs"

    # ADR-018 mission-only · 去 sessions FK + nullable（保留列作历史审计；sessions 表退役）
    session_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("missions.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(48), nullable=False)  # build_super / build_worker / install_skill / resume / ...
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    target_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    affected_supers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")  # ok / blocked / failed
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
