"""M2：MissionSchedule CRUD + 触发测试。

由于 APScheduler 在测试 lifespan 不启动（ASGITransport 不跑 lifespan），
这里只测：DB CRUD + 校验 + 手动 fire 走 mission_daemon.run_once 的桩。
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


async def _bootstrap(client: AsyncClient, auth: dict[str, str]) -> str:
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
                "name": "Sched Probe",
                "slug": "sched-probe",
                "supervisor_agent_id": sup.json()["id"],
            },
        )
    ).json()
    return proj["id"]


async def test_schedule_crud(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    pid = await _bootstrap(seeded_client, auth)

    # 初始空
    r = await seeded_client.get(f"/api/missions/{pid}/schedules", headers=auth)
    assert r.status_code == 200
    assert r.json() == []

    # 创建 cron
    cr = await seeded_client.post(
        f"/api/missions/{pid}/schedules",
        headers=auth,
        json={
            "name": "Every minute",
            "kind": "cron",
            "expr": "* * * * *",
        },
    )
    assert cr.status_code == 201, cr.text
    sid = cr.json()["id"]
    assert cr.json()["enabled"] is True
    assert cr.json()["fire_count"] == 0

    # 创建 interval
    cr2 = await seeded_client.post(
        f"/api/missions/{pid}/schedules",
        headers=auth,
        json={"name": "Every 30s", "kind": "interval", "expr": "30s"},
    )
    assert cr2.status_code == 201, cr2.text

    # 创建 event
    cr3 = await seeded_client.post(
        f"/api/missions/{pid}/schedules",
        headers=auth,
        json={"name": "On webhook", "kind": "event", "expr": "hello_world"},
    )
    assert cr3.status_code == 201, cr3.text

    # list 应 3 条
    lst = (await seeded_client.get(f"/api/missions/{pid}/schedules", headers=auth)).json()
    assert len(lst) == 3

    # disable
    upd = await seeded_client.put(
        f"/api/missions/{pid}/schedules/{sid}",
        headers=auth,
        json={"enabled": False},
    )
    assert upd.status_code == 200
    assert upd.json()["enabled"] is False

    # 删除
    de = await seeded_client.delete(
        f"/api/missions/{pid}/schedules/{sid}", headers=auth
    )
    assert de.status_code == 204

    lst2 = (await seeded_client.get(f"/api/missions/{pid}/schedules", headers=auth)).json()
    assert len(lst2) == 2


async def test_schedule_validation(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    pid = await _bootstrap(seeded_client, auth)

    # 非法 cron 表达式
    r = await seeded_client.post(
        f"/api/missions/{pid}/schedules",
        headers=auth,
        json={"name": "Bad cron", "kind": "cron", "expr": "not a cron"},
    )
    assert r.status_code in (400, 422), r.text

    # 非法 interval
    r2 = await seeded_client.post(
        f"/api/missions/{pid}/schedules",
        headers=auth,
        json={"name": "Bad interval", "kind": "interval", "expr": "30x"},
    )
    assert r2.status_code in (400, 422), r2.text

    # 非法 event 名称
    r3 = await seeded_client.post(
        f"/api/missions/{pid}/schedules",
        headers=auth,
        json={"name": "Bad event", "kind": "event", "expr": "Foo Bar"},
    )
    assert r3.status_code in (400, 422), r3.text


async def test_schedule_event_fire_requires_running_project(
    seeded_client: AsyncClient,
) -> None:
    """event 触发会走 fire_one；ADR-028 D4：project stopped → 调度器逻辑级 skip（不跑 run_once）。

    （D4 前是 run_once 抛 runtime_status ValueError；现在 fire_one 在调用 run_once 前按
    mission lifecycle 决定 run/skip，stopped→skip，更干净。schedule.enabled 不被改。）"""
    auth = await _auth(seeded_client)
    pid = await _bootstrap(seeded_client, auth)

    # 创建 event schedule
    await seeded_client.post(
        f"/api/missions/{pid}/schedules",
        headers=auth,
        json={"name": "Web ping", "kind": "event", "expr": "ping"},
    )

    # 触发：项目 stopped → fire_one lifecycle-gate skip；API 返回 200，不跑 run_once、不计数
    r = await seeded_client.post(
        f"/api/missions/{pid}/events/ping",
        headers=auth,
        json={"payload": {"foo": "bar"}},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert len(payload) == 1
    # D4：stopped 被调度器 skip（lifecycle_gate），不写 run_once 的 runtime 错、不计 fire_count
    assert payload[0]["fire_count"] == 0
    assert not payload[0]["last_error"]


async def test_schedule_event_fire_when_running(seeded_client: AsyncClient) -> None:
    """先 start，再 fire → run_once 成功 → fire_count + 1。"""
    auth = await _auth(seeded_client)
    pid = await _bootstrap(seeded_client, auth)
    await seeded_client.post(
        f"/api/missions/{pid}/schedules",
        headers=auth,
        json={"name": "Web ping", "kind": "event", "expr": "ping"},
    )
    # start
    await seeded_client.post(f"/api/missions/{pid}/lifecycle/start", headers=auth)
    # fire
    r = await seeded_client.post(
        f"/api/missions/{pid}/events/ping",
        headers=auth,
        json={"payload": {"foo": "bar"}},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload[0]["fire_count"] == 1
    assert payload[0]["last_fired_at"] is not None
    assert payload[0]["last_error"] is None

    # runtime.run_count 也 +1
    rt = await seeded_client.get(f"/api/missions/{pid}/runtime", headers=auth)
    assert rt.json()["run_count"] == 1

    # cleanup
    await seeded_client.post(f"/api/missions/{pid}/lifecycle/stop", headers=auth)


async def test_event_fire_unknown_returns_404(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    pid = await _bootstrap(seeded_client, auth)
    r = await seeded_client.post(
        f"/api/missions/{pid}/events/nothing",
        headers=auth,
        json={"payload": {}},
    )
    assert r.status_code == 404
