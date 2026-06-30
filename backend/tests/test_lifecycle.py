"""M1: Mission lifecycle / daemon tests。

覆盖：
- POST /api/missions/{id}/lifecycle/start → stopped → running
- 重复 start 幂等
- POST .../stop → running → stopped
- 重复 stop 幂等
- restart 等同 stop+start
- GET /api/missions/{id}/runtime 返回 MissionRuntimePublic
- 不存在的 project → 404
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _auth(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _bootstrap_project(client: AsyncClient, auth: dict[str, str]) -> str:
    """复用 test_projects._bootstrap 的轻量版本，建一个 1-node project。"""
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
    proj = (
        await client.post(
            "/api/missions/full",
            headers=auth,
            json={
                "name": "Lifecycle Probe",
                "slug": "lifecycle-probe",
                "supervisor_agent_id": sup.json()["id"],
            },
        )
    ).json()
    return proj["id"]


async def test_runtime_initial_stopped(seeded_client: AsyncClient) -> None:
    """新建 project：runtime_status='stopped'，mission_run_state 自动建空记录。"""
    auth = await _auth(seeded_client)
    pid = await _bootstrap_project(seeded_client, auth)

    detail = await seeded_client.get(f"/api/missions/detail/{pid}", headers=auth)
    assert detail.status_code == 200
    assert detail.json()["runtime_status"] == "stopped"

    rt = await seeded_client.get(f"/api/missions/{pid}/runtime", headers=auth)
    assert rt.status_code == 200
    body = rt.json()
    assert body["status"] == "stopped"
    assert body["run_count"] == 0


async def test_lifecycle_start_then_stop(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    pid = await _bootstrap_project(seeded_client, auth)

    # start
    r = await seeded_client.post(f"/api/missions/{pid}/lifecycle/start", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"
    assert r.json()["started_at"] is not None

    # 顶层 runtime_status 同步
    detail = await seeded_client.get(f"/api/missions/detail/{pid}", headers=auth)
    assert detail.json()["runtime_status"] == "running"

    # 再次 start —— 幂等，状态不变
    r2 = await seeded_client.post(f"/api/missions/{pid}/lifecycle/start", headers=auth)
    assert r2.status_code == 200
    assert r2.json()["status"] == "running"

    # stop
    r3 = await seeded_client.post(f"/api/missions/{pid}/lifecycle/stop", headers=auth)
    assert r3.status_code == 200
    assert r3.json()["status"] == "stopped"
    assert r3.json()["stopped_at"] is not None

    # 再次 stop —— 幂等
    r4 = await seeded_client.post(f"/api/missions/{pid}/lifecycle/stop", headers=auth)
    assert r4.status_code == 200
    assert r4.json()["status"] == "stopped"


async def test_lifecycle_restart(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    pid = await _bootstrap_project(seeded_client, auth)

    # 先 start
    await seeded_client.post(f"/api/missions/{pid}/lifecycle/start", headers=auth)
    # restart
    r = await seeded_client.post(
        f"/api/missions/{pid}/lifecycle/restart", headers=auth
    )
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    # cleanup
    await seeded_client.post(f"/api/missions/{pid}/lifecycle/stop", headers=auth)


async def test_lifecycle_unknown_project_404(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    bogus = "00000000-0000-0000-0000-000000000001"
    r = await seeded_client.post(
        f"/api/missions/{bogus}/lifecycle/start", headers=auth
    )
    assert r.status_code == 404

    r2 = await seeded_client.get(f"/api/missions/{bogus}/runtime", headers=auth)
    assert r2.status_code == 404


async def test_lifecycle_unknown_action_422(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    pid = await _bootstrap_project(seeded_client, auth)
    r = await seeded_client.post(
        f"/api/missions/{pid}/lifecycle/blowup", headers=auth
    )
    # FastAPI 对 Literal 入参校验失败 → 422
    assert r.status_code == 422
