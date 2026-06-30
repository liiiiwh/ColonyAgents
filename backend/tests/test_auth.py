"""Phase 1 Auth API 测试：login / refresh / me。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_login_success(seeded_client: AsyncClient, admin_credentials: dict[str, str]) -> None:
    resp = await seeded_client.post(
        "/api/auth/login",
        data=admin_credentials,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["refresh_token"]


async def test_login_wrong_password(seeded_client: AsyncClient) -> None:
    resp = await seeded_client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 401


async def test_login_missing_user(seeded_client: AsyncClient) -> None:
    resp = await seeded_client.post(
        "/api/auth/login",
        data={"username": "ghost", "password": "x"},
    )
    assert resp.status_code == 401


async def test_me_requires_token(client: AsyncClient) -> None:
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_returns_current_user(
    seeded_client: AsyncClient, admin_credentials: dict[str, str]
) -> None:
    login = await seeded_client.post("/api/auth/login", data=admin_credentials)
    token = login.json()["access_token"]
    resp = await seeded_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert me["username"] == "admin"
    assert me["role"] == "admin"


async def test_refresh_flow(seeded_client: AsyncClient, admin_credentials: dict[str, str]) -> None:
    login = await seeded_client.post("/api/auth/login", data=admin_credentials)
    refresh_token = login.json()["refresh_token"]

    resp = await seeded_client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["access_token"]
    assert data["refresh_token"]


async def test_refresh_invalid_token(seeded_client: AsyncClient) -> None:
    resp = await seeded_client.post(
        "/api/auth/refresh",
        json={"refresh_token": "not-a-jwt"},
    )
    assert resp.status_code == 401
