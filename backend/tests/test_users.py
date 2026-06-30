"""用户管理 API 测试 —— 权限矩阵 + 超级管理员专属删除 admin 规则。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _login(client: AsyncClient, username: str, password: str) -> str:
    # /api/auth/login 使用 OAuth2PasswordRequestForm → application/x-www-form-urlencoded
    r = await client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _create_user(
    client: AsyncClient,
    token: str,
    *,
    username: str,
    email: str,
    role: str = "user",
    password: str = "pass1234",
) -> dict:
    r = await client.post(
        "/api/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": username,
            "email": email,
            "password": password,
            "role": role,
            "is_active": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_non_admin_cannot_list_users(seeded_client: AsyncClient):
    """普通用户访问 /api/users 列表应 403。"""
    admin_token = await _login(seeded_client, "admin", "admin123")
    await _create_user(
        seeded_client, admin_token, username="alice", email="a@x.com", role="user"
    )
    user_token = await _login(seeded_client, "alice", "pass1234")
    r = await seeded_client.get(
        "/api/users", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cannot_delete_self(seeded_client: AsyncClient):
    admin_token = await _login(seeded_client, "admin", "admin123")
    me = (
        await seeded_client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"}
        )
    ).json()
    r = await seeded_client.delete(
        f"/api/users/{me['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 400
    assert "不能删除自己" in r.json()["detail"]


@pytest.mark.asyncio
async def test_regular_admin_cannot_delete_other_admin(seeded_client: AsyncClient):
    """普通 admin 不能删除其他 admin；只有超级管理员 (username='admin') 可以。"""
    super_token = await _login(seeded_client, "admin", "admin123")
    # 创建两个 admin
    admin1 = await _create_user(
        seeded_client, super_token, username="admin1", email="a1@x.com", role="admin"
    )
    admin2 = await _create_user(
        seeded_client, super_token, username="admin2", email="a2@x.com", role="admin"
    )
    # 以 admin1 身份尝试删除 admin2 —— 应被拒
    admin1_token = await _login(seeded_client, "admin1", "pass1234")
    r = await seeded_client.delete(
        f"/api/users/{admin2['id']}",
        headers={"Authorization": f"Bearer {admin1_token}"},
    )
    assert r.status_code == 400
    assert "超级管理员" in r.json()["detail"]


@pytest.mark.asyncio
async def test_super_admin_can_delete_other_admin(seeded_client: AsyncClient):
    super_token = await _login(seeded_client, "admin", "admin123")
    target = await _create_user(
        seeded_client, super_token, username="admin2", email="a2@x.com", role="admin"
    )
    r = await seeded_client.delete(
        f"/api/users/{target['id']}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_any_admin_can_delete_regular_user(seeded_client: AsyncClient):
    """普通 admin 可以删除 role=user 的普通账号。"""
    super_token = await _login(seeded_client, "admin", "admin123")
    admin1 = await _create_user(
        seeded_client, super_token, username="admin1", email="a1@x.com", role="admin"
    )
    assert admin1  # silence lint
    target = await _create_user(
        seeded_client, super_token, username="bob", email="b@x.com", role="user"
    )
    admin1_token = await _login(seeded_client, "admin1", "pass1234")
    r = await seeded_client.delete(
        f"/api/users/{target['id']}",
        headers={"Authorization": f"Bearer {admin1_token}"},
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_regular_admin_cannot_create_admin(seeded_client: AsyncClient):
    """普通 admin 创建 role='admin' 账号应被拒 400；创建 role='user' 正常。"""
    super_token = await _login(seeded_client, "admin", "admin123")
    # 先由超级管理员创建一个普通 admin
    await _create_user(
        seeded_client, super_token, username="admin1", email="a1@x.com", role="admin"
    )
    admin1_token = await _login(seeded_client, "admin1", "pass1234")
    # 普通 admin 试图创建另一个 admin 账号 —— 400
    r = await seeded_client.post(
        "/api/users",
        headers={"Authorization": f"Bearer {admin1_token}"},
        json={
            "username": "admin2",
            "email": "a2@x.com",
            "password": "pass1234",
            "role": "admin",
            "is_active": True,
        },
    )
    assert r.status_code == 400, r.text
    assert "超级管理员" in r.json()["detail"]
    # 改创建 role='user' —— 201
    r2 = await seeded_client.post(
        "/api/users",
        headers={"Authorization": f"Bearer {admin1_token}"},
        json={
            "username": "bob",
            "email": "b@x.com",
            "password": "pass1234",
            "role": "user",
            "is_active": True,
        },
    )
    assert r2.status_code == 201, r2.text


@pytest.mark.asyncio
async def test_regular_admin_cannot_promote_user_to_admin(seeded_client: AsyncClient):
    """普通 admin 通过 PUT 把 user 提升为 admin 应被拒 400。"""
    super_token = await _login(seeded_client, "admin", "admin123")
    await _create_user(
        seeded_client, super_token, username="admin1", email="a1@x.com", role="admin"
    )
    bob = await _create_user(
        seeded_client, super_token, username="bob", email="b@x.com", role="user"
    )
    admin1_token = await _login(seeded_client, "admin1", "pass1234")
    r = await seeded_client.put(
        f"/api/users/{bob['id']}",
        headers={"Authorization": f"Bearer {admin1_token}"},
        json={"role": "admin"},
    )
    assert r.status_code == 400, r.text
    assert "超级管理员" in r.json()["detail"]


@pytest.mark.asyncio
async def test_super_admin_cannot_delete_last_admin(seeded_client: AsyncClient):
    """即使是超级管理员，也不能删除系统中最后一个可用 admin（这里是自己，
    但自删有独立保护；此处构造：只有 admin 一个 admin，尝试删自己 → 400 自删保护先触发）。"""
    super_token = await _login(seeded_client, "admin", "admin123")
    me = (
        await seeded_client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {super_token}"}
        )
    ).json()
    r = await seeded_client.delete(
        f"/api/users/{me['id']}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert r.status_code == 400
