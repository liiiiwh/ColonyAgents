"""Phase 5 Mission API 测试（ADR-027 · 节点版退役，无节点 CRUD）。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _auth(client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _user_auth(client: AsyncClient, username: str, password: str = "pass1234") -> dict[str, str]:
    resp = await client.post("/api/auth/login", data={"username": username, "password": password})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_user(
    client: AsyncClient,
    auth: dict[str, str],
    *,
    username: str,
    email: str,
    role: str = "user",
    is_active: bool = True,
) -> dict:
    resp = await client.post(
        "/api/users",
        headers=auth,
        json={
            "username": username,
            "email": email,
            "password": "pass1234",
            "role": role,
            "is_active": is_active,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _bootstrap(client: AsyncClient, auth: dict[str, str]) -> dict[str, str]:
    """创建 provider + chat model + supervisor agent，返回 ids。"""
    p = await client.post(
        "/api/providers",
        headers=auth,
        json={"name": "prov", "provider_type": "openai", "api_key": "sk-x"},
    )
    pid = p.json()["id"]
    await client.post(f"/api/providers/{pid}/sync-models", headers=auth)
    models = (await client.get(f"/api/providers/{pid}/models", headers=auth)).json()
    chat = next(m for m in models if m["model_type"] == "chat")
    sup = await client.post(
        "/api/agents",
        headers=auth,
        json={"name": "Sup", "model_id": chat["id"]},
    )
    return {
        "model_id": chat["id"],
        "supervisor_id": sup.json()["id"],
    }


async def test_create_mission_and_slug_conflict(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    ids = await _bootstrap(seeded_client, auth)

    p = await seeded_client.post(
        "/api/missions/full",
        headers=auth,
        json={
            "name": "Demo Mission",
            "slug": "demo",
            "description": "演示项目",
            "supervisor_agent_id": ids["supervisor_id"],
        },
    )
    assert p.status_code == 201, p.text
    project = p.json()
    assert project["status"] == "draft"

    # slug 冲突
    dup = await seeded_client.post(
        "/api/missions/full",
        headers=auth,
        json={
            "name": "dup",
            "slug": "demo",
            "supervisor_agent_id": ids["supervisor_id"],
        },
    )
    assert dup.status_code == 409


async def test_activate_mission(seeded_client: AsyncClient) -> None:
    """ADR-027 · validate_workflow 只校验 supervisor（worker 运行时按 capability 发现）。"""
    auth = await _auth(seeded_client)
    ids = await _bootstrap(seeded_client, auth)
    p = await seeded_client.post(
        "/api/missions/full",
        headers=auth,
        json={
            "name": "Empty",
            "slug": "empty",
            "supervisor_agent_id": ids["supervisor_id"],
        },
    )
    pid = p.json()["id"]

    act = await seeded_client.post(f"/api/missions/{pid}/activate", headers=auth)
    assert act.status_code == 200
    payload = act.json()
    assert payload["ok"] is True
    assert payload["status"] == "active"


async def test_public_endpoint_visible_only_when_active(
    seeded_client: AsyncClient,
) -> None:
    auth = await _auth(seeded_client)
    ids = await _bootstrap(seeded_client, auth)
    p = (
        await seeded_client.post(
            "/api/missions/full",
            headers=auth,
            json={
                "name": "Public",
                "slug": "pub",
                "supervisor_agent_id": ids["supervisor_id"],
            },
        )
    ).json()
    # draft 状态 → 未激活不可访问（现在需要登录）
    notready = await seeded_client.get("/api/missions/public/pub", headers=auth)
    assert notready.status_code == 404

    await seeded_client.post(f"/api/missions/{p['id']}/activate", headers=auth)

    ok = await seeded_client.get("/api/missions/public/pub", headers=auth)
    assert ok.status_code == 200
    assert ok.json()["status"] == "active"
    # 未登录访问 → 401
    unauth = await seeded_client.get("/api/missions/public/pub")
    assert unauth.status_code == 401


async def test_deactivate_project(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    ids = await _bootstrap(seeded_client, auth)
    p = (
        await seeded_client.post(
            "/api/missions/full",
            headers=auth,
            json={
                "name": "Deact",
                "slug": "deact",
                "supervisor_agent_id": ids["supervisor_id"],
            },
        )
    ).json()
    await seeded_client.post(f"/api/missions/{p['id']}/activate", headers=auth)
    resp = await seeded_client.post(f"/api/missions/{p['id']}/deactivate", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"


async def test_active_project_visible_to_any_logged_in_user(
    seeded_client: AsyncClient,
) -> None:
    """Colony 共享工作台：active 项目对所有登录用户可见，无 ACL 过滤。"""
    admin_auth = await _auth(seeded_client)
    ids = await _bootstrap(seeded_client, admin_auth)
    await _create_user(
        seeded_client, admin_auth, username="alice", email="alice@example.com"
    )
    user_auth = await _user_auth(seeded_client, "alice")

    project = (
        await seeded_client.post(
            "/api/missions/full",
            headers=admin_auth,
            json={
                "name": "Shared Demo",
                "slug": "shared-demo",
                "supervisor_agent_id": ids["supervisor_id"],
            },
        )
    ).json()
    await seeded_client.post(
        f"/api/missions/{project['id']}/activate", headers=admin_auth
    )

    visible = await seeded_client.get("/api/missions/active", headers=user_auth)
    assert visible.status_code == 200
    assert any(item["slug"] == "shared-demo" for item in visible.json())

    public = await seeded_client.get(
        "/api/missions/public/shared-demo", headers=user_auth
    )
    assert public.status_code == 200
