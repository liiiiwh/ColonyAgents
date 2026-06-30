"""ADR-010 R3 · run_shell 不可变审计日志。

无人工授权、无沙箱姿态下，审计是唯一事后追溯：每次 run_shell（放行/拦截）都记一行。
"""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ShellAuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "shell_audit_log"

    #: 谁发起（如 builder:<session_id>）
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 守门结果
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    layer: Mapped[str | None] = mapped_column(String(32), nullable=True)  # denylist / llm_gate
    rule: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gate_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 执行结果（拦截则 None）
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
