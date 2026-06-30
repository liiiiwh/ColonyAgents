"""mcp_autostart.autostart_local_mcp_servers · 启动期本地 http MCP 自动拉起编排

只测编排逻辑（探活/spawn 用 monkeypatch 替掉，不真起子进程）：
- 有 startup_command + 已活 → reused，不 spawn
- 有 startup_command + 没活 → spawn，成功计 started
- http 但无 startup_command（远程）→ 跳过
- 非 http / disabled → 跳过
"""
import pytest

from app.models.skill import MCPServer
from app.services import mcp_autostart


async def _mk(db, **kw):
    s = MCPServer(
        name=kw["name"],
        server_type=kw.get("server_type", "http"),
        url=kw.get("url", "http://127.0.0.1:18060/mcp"),
        is_enabled=kw.get("is_enabled", True),
        startup_command=kw.get("startup_command"),
        startup_cwd=kw.get("startup_cwd"),
    )
    db.add(s)
    await db.flush()
    return s


@pytest.mark.asyncio
async def test_reuse_alive_does_not_spawn(db_session, monkeypatch):
    await _mk(db_session, name="alive-mcp", startup_command=["/bin/echo", "x"])
    spawned = []
    monkeypatch.setattr(mcp_autostart, "_is_alive", lambda url, timeout=2.0: _coro(True))
    monkeypatch.setattr(mcp_autostart, "_spawn_and_wait",
                        lambda s, wait_seconds=20: _coro(spawned.append(s.name) or True))
    res = await mcp_autostart.autostart_local_mcp_servers(db_session)
    assert res["reused"] == ["alive-mcp"]
    assert spawned == []


@pytest.mark.asyncio
async def test_dead_with_startup_gets_spawned(db_session, monkeypatch):
    await _mk(db_session, name="dead-mcp", startup_command=["/bin/echo", "x"])
    monkeypatch.setattr(mcp_autostart, "_is_alive", lambda url, timeout=2.0: _coro(False))
    monkeypatch.setattr(mcp_autostart, "_spawn_and_wait", lambda s, wait_seconds=20: _coro(True))
    res = await mcp_autostart.autostart_local_mcp_servers(db_session)
    assert res["started"] == ["dead-mcp"]


@pytest.mark.asyncio
async def test_no_startup_command_skipped(db_session, monkeypatch):
    await _mk(db_session, name="remote-mcp", startup_command=None)
    monkeypatch.setattr(mcp_autostart, "_is_alive", lambda url, timeout=2.0: _coro(False))
    called = []
    monkeypatch.setattr(mcp_autostart, "_spawn_and_wait",
                        lambda s, wait_seconds=20: _coro(called.append(s.name) or True))
    res = await mcp_autostart.autostart_local_mcp_servers(db_session)
    assert res == {"started": [], "reused": [], "failed": []}
    assert called == []


@pytest.mark.asyncio
async def test_stdio_and_disabled_skipped(db_session, monkeypatch):
    await _mk(db_session, name="stdio-mcp", server_type="stdio", startup_command=["x"])
    await _mk(db_session, name="off-mcp", is_enabled=False, startup_command=["x"])
    monkeypatch.setattr(mcp_autostart, "_is_alive", lambda url, timeout=2.0: _coro(False))
    monkeypatch.setattr(mcp_autostart, "_spawn_and_wait", lambda s, wait_seconds=20: _coro(True))
    res = await mcp_autostart.autostart_local_mcp_servers(db_session)
    assert res["started"] == [] and res["reused"] == [] and res["failed"] == []


async def _coro(v):
    return v
