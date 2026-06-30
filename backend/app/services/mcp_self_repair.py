"""Tiered self-repair for MCP tool calls.

An MCP server going unreachable used to either silently drop the tool (load time) or bubble a
raw error to the LLM (call time) with no healing. This wraps each MCP tool so a failure is
handled in tiers:

  1. **Retry / reconnect** — retry the call a few times (each MCP call opens a fresh session, so a
     retry naturally reconnects); for local servers, attempt an autostart respawn first.
  2. **Report to Worker-Optimization** — on persistent failure, append a lightweight degradation
     signal to the Colony Worker Optimization mission (no per-call LLM turn) so the worker-opt
     super addresses it on its next tick.
  3. **Escalate to Builder** — a load-time total outage (server unreachable + autostart failed)
     escalates to Builder to fix the integration/binding.

The wrapper returns a structured error string to the LLM rather than raising, so the agent learns
the tool is degraded (and that self-repair was triggered) and can adapt this turn.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_RETRIES = 2


async def _report_to_worker_opt(server_name: str, err: Exception, ctx: Any) -> None:
    """Tier 2 — best-effort lightweight signal to the worker-opt mission. Never raises."""
    try:
        if ctx is None or getattr(ctx, "db_factory", None) is None:
            return
        from app.services import worker_health_service
        async with ctx.db_factory() as db:
            await worker_health_service.record_worker_issue(
                db,
                capability=f"mcp:{server_name}",
                evidence=f"MCP 工具调用持续失败：{type(err).__name__}: {err}",
                severity="warn",
                source="mcp_self_repair",
            )
    except Exception:
        logger.exception("[mcp_self_repair] report_to_worker_opt failed (不阻塞)")


def wrap_tool_coroutine(
    orig_coro,
    *,
    tool_name: str,
    server_name: str,
    ctx: Any,
    retries: int = _DEFAULT_RETRIES,
    sleep=asyncio.sleep,
):
    """Return a coroutine wrapping `orig_coro` with retry → report-to-worker-opt. Pure enough to
    unit-test: inject `sleep` to avoid real backoff and a fake `orig_coro` to drive failures."""

    async def _wrapped(*args, **kwargs):
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return await orig_coro(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — any MCP transport/tool error
                last_exc = e
                logger.warning(
                    "[mcp_self_repair] %s@%s call failed (attempt %d/%d): %s",
                    tool_name, server_name, attempt + 1, retries + 1, e,
                )
                if attempt < retries:
                    await sleep(0.5 * (attempt + 1))  # backoff; next call opens a fresh session
        # exhausted → tier 2
        await _report_to_worker_opt(server_name, last_exc, ctx)
        return (
            f"⚠️ MCP 工具 `{tool_name}`（server={server_name}）调用失败，已自动重试 {retries} 次并"
            f"上报 Colony Worker Optimization 自修复。错误：{type(last_exc).__name__}: {last_exc}。"
            f"请改用其它可用工具继续，或稍后再试该 MCP。"
        )

    return _wrapped


def wrap_mcp_tools(tools: list, *, ctx: Any, server_of=None) -> list:
    """Mutate each MCP tool's coroutine in place with the self-repair wrapper (preserves the
    tool's name/description/args_schema so the LLM contract is unchanged). `server_of(tool)` maps
    a tool to its server name; defaults to the tool name."""
    for t in tools:
        orig = getattr(t, "coroutine", None)
        if orig is None:
            continue
        name = getattr(t, "name", "mcp_tool")
        server = (server_of(t) if server_of else None) or name
        t.coroutine = wrap_tool_coroutine(orig, tool_name=name, server_name=server, ctx=ctx)
    return tools
