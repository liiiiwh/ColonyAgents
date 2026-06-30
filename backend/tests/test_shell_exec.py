"""ADR-010 R3 · execute_guarded_shell：守门→（拦截+审计）或（执行+审计）。

judge 注入 mock；用无害命令验真实执行；审计行始终落库（放行/拦截都记）。
"""
import pytest
from sqlalchemy import select

from app.models.shell_audit import ShellAuditLog
from app.services.shell_exec import execute_guarded_shell


async def _allow_judge(cmd, reason):
    return {"allow": True, "reason": "ok"}


@pytest.mark.asyncio
async def test_blocked_command_audited_not_executed(db_session):
    res = await execute_guarded_shell(
        "rm -rf /tmp/should_not_run", reason="x",
        judge=_allow_judge, db=db_session, actor="builder:test",
    )
    assert res["ok"] is False
    assert res["blocked"] is True
    assert res["exit_code"] is None  # 从未执行

    rows = (await db_session.execute(select(ShellAuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].allowed is False
    assert rows[0].layer == "denylist"
    assert rows[0].actor == "builder:test"


@pytest.mark.asyncio
async def test_allowed_command_executes_and_audits(db_session):
    res = await execute_guarded_shell(
        "echo colony-ready", reason="probe",
        judge=_allow_judge, db=db_session, actor="builder:test",
    )
    assert res["ok"] is True
    assert res["blocked"] is False
    assert res["exit_code"] == 0
    assert "colony-ready" in res["stdout"]

    row = (await db_session.execute(select(ShellAuditLog))).scalars().one()
    assert row.allowed is True
    assert row.layer == "llm_gate"
    assert "colony-ready" in (row.stdout or "")
    assert row.duration_ms is not None
