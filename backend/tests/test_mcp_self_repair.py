"""ADR-018 follow-up · tiered MCP self-repair (retry → report Worker-Opt)."""
from __future__ import annotations

import pytest

from app.services import mcp_self_repair

pytestmark = pytest.mark.asyncio


async def _nosleep(_):  # avoid real backoff
    return None


async def test_retries_then_succeeds():
    calls = {"n": 0}

    async def flaky(**kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("mcp down")
        return "ok"

    wrapped = mcp_self_repair.wrap_tool_coroutine(
        flaky, tool_name="t", server_name="s", ctx=None, retries=2, sleep=_nosleep)
    assert await wrapped() == "ok"
    assert calls["n"] == 2  # failed once, retried, succeeded


async def test_persistent_failure_reports_and_returns_error(monkeypatch):
    reported = {}

    async def fake_report(server_name, err, ctx):
        reported["server"] = server_name

    monkeypatch.setattr(mcp_self_repair, "_report_to_worker_opt", fake_report)

    async def always_fail(**kw):
        raise TimeoutError("unreachable")

    wrapped = mcp_self_repair.wrap_tool_coroutine(
        always_fail, tool_name="search", server_name="brave", ctx=object(), retries=2, sleep=_nosleep)
    out = await wrapped()
    assert reported.get("server") == "brave"      # tier-2 report fired
    assert "search" in out and "自修复" in out      # structured error returned to the LLM, not raised


async def test_wrap_mcp_tools_preserves_name_and_swaps_coroutine():
    class _T:
        def __init__(self):
            self.name = "fetch"
            async def _c(**kw):
                raise RuntimeError("x")
            self.coroutine = _c

    t = _T()
    orig = t.coroutine
    mcp_self_repair.wrap_mcp_tools([t], ctx=None)
    assert t.name == "fetch"          # contract preserved
    assert t.coroutine is not orig    # coroutine swapped for the self-repair wrapper
