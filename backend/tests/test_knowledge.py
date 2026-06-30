"""Phase 7 Knowledge API 测试。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _auth(client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _bootstrap_embed_model(client: AsyncClient, auth: dict[str, str]) -> str:
    p = await client.post(
        "/api/providers",
        headers=auth,
        json={"name": "prov-kb", "provider_type": "openai", "api_key": "sk-x"},
    )
    pid = p.json()["id"]
    await client.post(f"/api/providers/{pid}/sync-models", headers=auth)
    models = (await client.get(f"/api/providers/{pid}/models", headers=auth)).json()
    embed = next(m for m in models if m["model_type"] == "embedding")
    return embed["id"]


async def test_create_kb_and_index_and_search(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    embed_id = await _bootstrap_embed_model(seeded_client, auth)

    # 创建
    kb = await seeded_client.post(
        "/api/knowledge",
        headers=auth,
        json={
            "name": "玩具设计知识",
            "collection_name": "toy_design",
            "description": "设计素材与材料说明",
            "embedding_model_id": embed_id,
        },
    )
    assert kb.status_code == 201, kb.text
    kb_id = kb.json()["id"]

    # 索引 2 个文档
    doc1 = await seeded_client.post(
        f"/api/knowledge/{kb_id}/documents",
        headers=auth,
        json={
            "filename": "material.md",
            "content": ("# 材料说明\n玩具主要使用 ABS 塑料和 TPE 软胶。" * 20),
        },
    )
    assert doc1.status_code == 201, doc1.text
    assert doc1.json()["chunk_count"] > 0
    assert doc1.json()["status"] == "indexed"

    doc2 = await seeded_client.post(
        f"/api/knowledge/{kb_id}/documents",
        headers=auth,
        json={
            "filename": "process.md",
            "content": ("生产流程：注塑 → 喷涂 → 装配 → 质检。" * 10),
        },
    )
    assert doc2.status_code == 201

    # 列文档
    docs = await seeded_client.get(f"/api/knowledge/{kb_id}/documents", headers=auth)
    assert len(docs.json()) == 2

    # 检索
    search = await seeded_client.post(
        f"/api/knowledge/{kb_id}/search",
        headers=auth,
        json={"query": "生产流程", "top_k": 3},
    )
    assert search.status_code == 200, search.text
    hits = search.json()["hits"]
    assert len(hits) >= 1
    assert all("score" in h for h in hits)


async def test_create_kb_requires_embedding_model(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    # 用 chat model 而非 embedding
    p = await seeded_client.post(
        "/api/providers",
        headers=auth,
        json={"name": "prov-wrong", "provider_type": "openai", "api_key": "sk-x"},
    )
    await seeded_client.post(f"/api/providers/{p.json()['id']}/sync-models", headers=auth)
    models = (
        await seeded_client.get(f"/api/providers/{p.json()['id']}/models", headers=auth)
    ).json()
    chat = next(m for m in models if m["model_type"] == "chat")

    resp = await seeded_client.post(
        "/api/knowledge",
        headers=auth,
        json={
            "name": "bad",
            "collection_name": "bad_coll",
            "embedding_model_id": chat["id"],
        },
    )
    assert resp.status_code == 400


async def test_delete_kb_cascades(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    embed_id = await _bootstrap_embed_model(seeded_client, auth)
    kb = (
        await seeded_client.post(
            "/api/knowledge",
            headers=auth,
            json={
                "name": "tmp",
                "collection_name": "tmp_coll",
                "embedding_model_id": embed_id,
            },
        )
    ).json()
    await seeded_client.post(
        f"/api/knowledge/{kb['id']}/documents",
        headers=auth,
        json={"filename": "a.txt", "content": "hello"},
    )
    dele = await seeded_client.delete(f"/api/knowledge/{kb['id']}", headers=auth)
    assert dele.status_code == 204
    miss = await seeded_client.get(f"/api/knowledge/{kb['id']}", headers=auth)
    assert miss.status_code == 404
