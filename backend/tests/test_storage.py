"""Phase 7 Storage API 测试（使用 InMemory backend）。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.storage_service import make_inmemory_backend, set_storage

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def inject_inmemory_backend():
    backend = make_inmemory_backend()
    set_storage(backend)
    yield backend
    set_storage(None)  # type: ignore[arg-type]


async def _auth(client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_upload_list_download_delete(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)

    # upload
    files = {"file": ("test.md", b"# hello\ncolony", "text/markdown")}
    up = await seeded_client.post("/api/storage/upload", headers=auth, files=files)
    assert up.status_code == 200, up.text
    assert up.json()["key"] == "test.md"
    assert up.json()["size"] == len(b"# hello\ncolony")

    # list
    lst = await seeded_client.get("/api/storage/files", headers=auth)
    assert lst.status_code == 200
    assert any(o["key"] == "test.md" for o in lst.json())

    # download
    dl = await seeded_client.get("/api/storage/download", headers=auth, params={"key": "test.md"})
    assert dl.status_code == 200
    assert dl.content == b"# hello\ncolony"

    # presigned
    url_resp = await seeded_client.get("/api/storage/url", headers=auth, params={"key": "test.md"})
    assert url_resp.status_code == 200
    assert url_resp.json()["url"].startswith("memory://test.md")

    # delete
    dele = await seeded_client.delete("/api/storage/files", headers=auth, params={"key": "test.md"})
    assert dele.status_code == 204

    # 再下载应 404
    miss = await seeded_client.get("/api/storage/download", headers=auth, params={"key": "test.md"})
    assert miss.status_code == 404
