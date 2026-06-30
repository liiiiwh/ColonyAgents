"""ADR-010 R2 wiring · default_probe / default_remediate 真实探针与补救。

http_health 探针可 mock；env_present 查环境；server_up 补救复用 startup_command spawn。
"""
import pytest

from app.models.skill import MCPServer
from app.services import readiness as rd


@pytest.mark.asyncio
async def test_http_health_probe_uses_liveness(monkeypatch):
    server = MCPServer(name="x", server_type="http", url="http://127.0.0.1:18060/mcp",
                       is_enabled=True, startup_command=["/x"])
    monkeypatch.setattr(rd, "_is_alive", lambda url, timeout=2.0: _coro(True))
    ok = await rd.default_probe({"id": "server_up", "kind": "auto-shell",
                                 "probe": {"type": "http_health"}}, server)
    assert ok is True


@pytest.mark.asyncio
async def test_env_present_probe(monkeypatch):
    server = MCPServer(name="x", server_type="http", url="http://x", is_enabled=True)
    monkeypatch.setenv("MY_TEST_KEY", "v")
    ok = await rd.default_probe({"id": "secret:MY_TEST_KEY", "kind": "human-secret",
                                "probe": {"type": "env_present", "key": "MY_TEST_KEY"}}, server)
    assert ok is True
    missing = await rd.default_probe({"id": "secret:NOPE", "kind": "human-secret",
                                     "probe": {"type": "env_present", "key": "NOPE_KEY_X"}}, server)
    assert missing is False


@pytest.mark.asyncio
async def test_ensure_ready_posts_human_card_for_pending(db_session, monkeypatch):
    server = MCPServer(name="xhs-mcp", server_type="http", url="http://x/mcp", is_enabled=True,
                       startup_command=["/x"],
                       readiness_manifest={"deployment": "local", "requirements": [
                           {"id": "logged_in", "kind": "human-qr", "probe": {"type": "mcp_tool"}, "remediation": {}},
                       ]})
    db_session.add(server)
    await db_session.flush()
    # 未登录
    monkeypatch.setattr(rd, "default_probe", lambda req, srv: _coro(False))
    posted = []

    async def fake_poster(db, mission_id, srv, requirement):
        posted.append((srv.name, requirement["id"]))

    res = await rd.ensure_ready_for_server(
        db_session, server.id, mission_id="11111111-1111-1111-1111-111111111111",
        post_human_action=fake_poster,
    )
    assert res["ready"] is False
    assert posted == [("xhs-mcp", "logged_in")]


async def _coro(v):
    return v
