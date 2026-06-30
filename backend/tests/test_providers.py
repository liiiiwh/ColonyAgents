"""Phase 2 providers API 测试。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _login(client: AsyncClient) -> str:
    resp = await client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _auth(client: AsyncClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {await _login(client)}"}


async def test_providers_requires_admin(client: AsyncClient) -> None:
    resp = await client.get("/api/providers")
    assert resp.status_code == 401


async def test_create_list_update_delete_provider(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)

    create = await seeded_client.post(
        "/api/providers",
        headers=auth,
        json={
            "name": "openai-main",
            "provider_type": "openai",
            "api_key": "sk-test-123",
            "base_url": "https://api.openai.com/v1",
            "extra_config": {"organization": "org-abc"},
            "is_enabled": True,
        },
    )
    assert create.status_code == 201, create.text
    created = create.json()
    provider_id = created["id"]
    assert created["has_api_key"] is True
    # 响应不应泄露明文 api_key
    assert "api_key" not in created

    # 列表
    lst = await seeded_client.get("/api/providers", headers=auth)
    assert lst.status_code == 200
    names = [p["name"] for p in lst.json()]
    assert "openai-main" in names

    # 同名冲突
    dup = await seeded_client.post(
        "/api/providers",
        headers=auth,
        json={"name": "openai-main", "provider_type": "openai", "api_key": "x"},
    )
    assert dup.status_code == 409

    # 更新（仅改描述字段，不替换 key）
    upd = await seeded_client.put(
        f"/api/providers/{provider_id}",
        headers=auth,
        json={"base_url": "https://proxy.example.com/v1", "is_enabled": False},
    )
    assert upd.status_code == 200
    assert upd.json()["base_url"] == "https://proxy.example.com/v1"
    assert upd.json()["is_enabled"] is False

    # 删除
    dele = await seeded_client.delete(f"/api/providers/{provider_id}", headers=auth)
    assert dele.status_code == 204

    # 再次 GET 应 404
    miss = await seeded_client.get(f"/api/providers/{provider_id}", headers=auth)
    assert miss.status_code == 404


async def test_sync_models_and_list(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)

    p = await seeded_client.post(
        "/api/providers",
        headers=auth,
        json={"name": "openai-sync", "provider_type": "openai", "api_key": "sk-x"},
    )
    assert p.status_code == 201
    pid = p.json()["id"]

    sync = await seeded_client.post(f"/api/providers/{pid}/sync-models", headers=auth)
    assert sync.status_code == 200, sync.text
    payload = sync.json()
    assert payload["synced"] > 0

    # 列模型
    lst = await seeded_client.get(f"/api/providers/{pid}/models", headers=auth)
    assert lst.status_code == 200
    models = lst.json()
    assert any(m["model_id"] == "gpt-4o" for m in models)
    assert any(m["model_type"] == "embedding" for m in models)

    # 幂等：再次 sync 不产生重复
    sync2 = await seeded_client.post(f"/api/providers/{pid}/sync-models", headers=auth)
    assert sync2.status_code == 200
    lst2 = await seeded_client.get(f"/api/providers/{pid}/models", headers=auth)
    assert len(lst2.json()) == len(models)

    # 禁用某个模型
    target_id = next(m["id"] for m in models if m["model_id"] == "gpt-4o")
    patch = await seeded_client.patch(
        f"/api/providers/{pid}/models/{target_id}",
        headers=auth,
        json={"is_enabled": False},
    )
    assert patch.status_code == 200
    assert patch.json()["is_enabled"] is False


async def test_api_key_encrypted_at_rest(seeded_client: AsyncClient, db_session) -> None:
    """验证 DB 中的 api_key 字段存放的是 Fernet 密文，非明文。"""
    from sqlalchemy import select

    from app.models.provider import LLMProvider

    auth = await _auth(seeded_client)
    create = await seeded_client.post(
        "/api/providers",
        headers=auth,
        json={"name": "secret-provider", "provider_type": "custom", "api_key": "plain-secret-abc"},
    )
    assert create.status_code == 201

    result = await db_session.execute(
        select(LLMProvider).where(LLMProvider.name == "secret-provider")
    )
    provider = result.scalar_one()
    assert provider.api_key != "plain-secret-abc"
    # Fernet token 特征：以 "gAAAAA" 开头的 base64（版本 0x80）
    assert provider.api_key.startswith("gAAAAA")


async def test_custom_provider_empty_catalog_returns_zero(
    seeded_client: AsyncClient,
) -> None:
    """custom provider 的 fake fetcher 返回空列表，sync 应返回 synced=0。"""
    auth = await _auth(seeded_client)
    p = await seeded_client.post(
        "/api/providers",
        headers=auth,
        json={"name": "empty", "provider_type": "custom", "api_key": "x"},
    )
    sync = await seeded_client.post(f"/api/providers/{p.json()['id']}/sync-models", headers=auth)
    assert sync.status_code == 200
    assert sync.json()["synced"] == 0


async def test_sync_failure_returns_502(seeded_client: AsyncClient, monkeypatch) -> None:
    """真实 fetcher 抛异常时，/sync-models 应返回 502 并给出错误原因。"""
    from app.services import provider_service
    from app.services.provider_service import ProviderSyncError

    async def _boom(**_kwargs):
        raise ProviderSyncError("模拟网络失败")

    monkeypatch.setitem(provider_service.MODEL_FETCHERS, "openai", _boom)

    auth = await _auth(seeded_client)
    p = await seeded_client.post(
        "/api/providers",
        headers=auth,
        json={"name": "broken", "provider_type": "openai", "api_key": "sk-x"},
    )
    resp = await seeded_client.post(f"/api/providers/{p.json()['id']}/sync-models", headers=auth)
    assert resp.status_code == 502
    assert "模拟网络失败" in resp.json()["detail"]


async def test_manual_add_model(seeded_client: AsyncClient) -> None:
    """POST /api/providers/{id}/models 可绕过 sync 手工添加。"""
    auth = await _auth(seeded_client)
    p = await seeded_client.post(
        "/api/providers",
        headers=auth,
        json={"name": "manual", "provider_type": "custom", "api_key": "x"},
    )
    pid = p.json()["id"]
    add = await seeded_client.post(
        f"/api/providers/{pid}/models",
        headers=auth,
        json={
            "model_id": "my-local-llm",
            "display_name": "My Local LLM",
            "model_type": "chat",
            "context_window": 8192,
        },
    )
    assert add.status_code == 201, add.text
    assert add.json()["model_id"] == "my-local-llm"

    # 重复添加同名应 409
    dup = await seeded_client.post(
        f"/api/providers/{pid}/models",
        headers=auth,
        json={"model_id": "my-local-llm", "display_name": "dup", "model_type": "chat"},
    )
    assert dup.status_code == 409
