"""Phase 3 MCP Server API 测试。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _auth(client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_crud_stdio_mcp(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    create = await seeded_client.post(
        "/api/mcp-servers",
        headers=auth,
        json={
            "name": "fs",
            "description": "filesystem MCP",
            "server_type": "stdio",
            "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            "env_vars": {"LOG_LEVEL": "info"},
            "is_enabled": True,
        },
    )
    assert create.status_code == 201, create.text
    sid = create.json()["id"]

    # test 端点
    test = await seeded_client.post(f"/api/mcp-servers/{sid}/test", headers=auth)
    assert test.status_code == 200
    payload = test.json()
    assert payload["reachable"] is True
    assert payload["error"] is None

    # 修改 command
    upd = await seeded_client.put(
        f"/api/mcp-servers/{sid}",
        headers=auth,
        json={"command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/var"]},
    )
    assert upd.status_code == 200

    # 删除
    dele = await seeded_client.delete(f"/api/mcp-servers/{sid}", headers=auth)
    assert dele.status_code == 204


async def test_stdio_without_command_rejected(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    resp = await seeded_client.post(
        "/api/mcp-servers",
        headers=auth,
        json={"name": "bad", "server_type": "stdio"},
    )
    assert resp.status_code == 400


async def test_http_mcp(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    create = await seeded_client.post(
        "/api/mcp-servers",
        headers=auth,
        json={
            "name": "remote",
            "server_type": "http",
            "url": "https://mcp.example.com/mcp",
            "headers": {"Authorization": "Bearer xxx"},
            "is_enabled": True,
        },
    )
    assert create.status_code == 201
    sid = create.json()["id"]
    test = await seeded_client.post(f"/api/mcp-servers/{sid}/test", headers=auth)
    assert test.json()["reachable"] is True


async def test_http_without_url_rejected(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    resp = await seeded_client.post(
        "/api/mcp-servers",
        headers=auth,
        json={"name": "bad", "server_type": "http"},
    )
    assert resp.status_code == 400
