"""ADR-010 R3 · execute_guarded_shell：守门 → 执行 → 审计。

姿态（ADR-010）：通用 shell、Builder 作用域、无人工授权、无沙箱。唯一预防层 =
denylist 硬拦 + 简单快 LLM 门（default-deny），唯一事后追溯 = 不可变审计日志。
judge / db 注入便于独测。
"""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.shell_safety import evaluate_command_safety
from app.models.shell_audit import ShellAuditLog

logger = logging.getLogger(__name__)

#: 单条 stdout/stderr 入库上限（防爆库）
_OUTPUT_CAP = 16_000


async def execute_guarded_shell(
    command: str,
    *,
    cwd: str | None = None,
    reason: str | None = None,
    judge,
    db: AsyncSession,
    actor: str | None = None,
    timeout: float = 60.0,
) -> dict:
    verdict = await evaluate_command_safety(command, reason, judge=judge)
    audit = ShellAuditLog(
        actor=actor, command=command, reason=reason,
        allowed=verdict.allowed, layer=verdict.layer, rule=verdict.rule,
        gate_reason=verdict.reason,
    )

    if not verdict.allowed:
        db.add(audit)
        await db.commit()
        await db.refresh(audit)
        return {
            "ok": False, "blocked": True, "exit_code": None,
            "layer": verdict.layer, "rule": verdict.rule,
            "reason": verdict.reason, "audit_id": str(audit.id),
        }

    started = time.time()
    try:
        proc = await asyncio.create_subprocess_shell(
            command, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        exit_code = proc.returncode
        stdout = (out_b or b"").decode(errors="replace")[:_OUTPUT_CAP]
        stderr = (err_b or b"").decode(errors="replace")[:_OUTPUT_CAP]
    except asyncio.TimeoutError:
        exit_code, stdout, stderr = None, "", f"timeout>{timeout}s"
    except Exception as exc:  # noqa: BLE001
        exit_code, stdout, stderr = None, "", f"{type(exc).__name__}: {exc}"

    audit.exit_code = exit_code
    audit.stdout = stdout
    audit.stderr = stderr
    audit.duration_ms = int((time.time() - started) * 1000)
    db.add(audit)
    await db.commit()
    await db.refresh(audit)

    return {
        "ok": exit_code == 0, "blocked": False, "exit_code": exit_code,
        "stdout": stdout, "stderr": stderr, "audit_id": str(audit.id),
    }
