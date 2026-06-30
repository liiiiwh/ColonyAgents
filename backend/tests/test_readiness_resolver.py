"""ADR-010 R2 · ensure_ready resolver：走 manifest → 探针 → 派发补救。

probe_fn / remediate_fn 注入便于独测（真实版调 MCP 工具 / http / run_shell / human-card）。
"""
import pytest

from app.models.skill import MCPServer
from app.services.readiness_resolver import ensure_ready


async def _mk_server(db, manifest):
    s = MCPServer(name="t-mcp", server_type="http", url="http://x/mcp",
                  is_enabled=True, readiness_manifest=manifest)
    db.add(s)
    await db.flush()
    return s


_MANIFEST_SERVER_ONLY = {
    "deployment": "local",
    "requirements": [{"id": "server_up", "kind": "auto-shell", "probe": {}, "remediation": {}}],
}


@pytest.mark.asyncio
async def test_all_satisfied_ready(db_session):
    s = await _mk_server(db_session, _MANIFEST_SERVER_ONLY)
    remediated = []

    async def probe(req, server):
        return True  # 全满足

    async def remediate(req, server):
        remediated.append(req["id"])
        return True

    res = await ensure_ready(db_session, s.id, probe_fn=probe, remediate_fn=remediate)
    assert res["ready"] is True
    assert res["pending"] == []
    assert remediated == []  # 已满足不补救


@pytest.mark.asyncio
async def test_autoshell_remediate_then_reprobe(db_session):
    s = await _mk_server(db_session, _MANIFEST_SERVER_ONLY)
    state = {"up": False}

    async def probe(req, server):
        return state["up"]

    async def remediate(req, server):
        state["up"] = True  # 拉起成功
        return True

    res = await ensure_ready(db_session, s.id, probe_fn=probe, remediate_fn=remediate)
    assert res["ready"] is True
    assert res["actions_taken"] == ["server_up"]
    assert res["pending"] == []


@pytest.mark.asyncio
async def test_autoshell_remediate_fails_pending(db_session):
    s = await _mk_server(db_session, _MANIFEST_SERVER_ONLY)

    async def probe(req, server):
        return False  # 始终探不到

    async def remediate(req, server):
        return False  # 拉起失败

    res = await ensure_ready(db_session, s.id, probe_fn=probe, remediate_fn=remediate)
    assert res["ready"] is False
    assert {"id": "server_up", "kind": "auto-shell"} in res["pending"]


@pytest.mark.asyncio
async def test_human_qr_goes_pending_not_remediated(db_session):
    s = await _mk_server(db_session, {
        "deployment": "local",
        "requirements": [{"id": "logged_in", "kind": "human-qr", "probe": {}, "remediation": {}}],
    })
    remediated = []

    async def probe(req, server):
        return False  # 未登录

    async def remediate(req, server):
        remediated.append(req["id"])
        return True

    res = await ensure_ready(db_session, s.id, probe_fn=probe, remediate_fn=remediate)
    assert res["ready"] is False
    assert res["pending"] == [{"id": "logged_in", "kind": "human-qr"}]
    assert remediated == []  # human-qr 不走 auto remediate
