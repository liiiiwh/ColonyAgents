"""M7: mission_test_runner clone + run + cleanup 测试。

LLM judge 在 sqlite 测试环境下没有可用 provider → 降级为 needs_review。
我们只断言：probe 数据正确 + sandbox 被清理 + judge 字段存在。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mission import Mission
from app.services import mission_test_runner

pytestmark = pytest.mark.asyncio


async def _auth(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _bootstrap_project(client: AsyncClient, auth: dict[str, str]) -> str:
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
    wrk = await client.post(
        "/api/agents",
        headers=auth,
        json={"name": "Wrk", "model_id": chat["id"]},
    )
    proj = (
        await client.post(
            "/api/missions/full",
            headers=auth,
            json={
                "name": "Smoke Probe",
                "slug": "smoke-probe",
                "supervisor_agent_id": sup.json()["id"],
            },
        )
    ).json()
    # 加一个节点，保证 validate_workflow 不报错
    await client.post(
        f"/api/missions/{proj['id']}/nodes",
        headers=auth,
        json={"agent_id": wrk.json()["id"], "node_name": "n1", "node_order": 0},
    )
    return proj["id"]


async def test_smoke_test_clone_run_cleanup(
    seeded_client: AsyncClient, db_session: AsyncSession
) -> None:
    auth = await _auth(seeded_client)
    pid = await _bootstrap_project(seeded_client, auth)

    res = await mission_test_runner.run_smoke_test(
        db_session, uuid.UUID(pid), scenario_text="测试场景：跑通"
    )
    probe = res["probe"]
    judge = res["judge"]

    # probe 内容
    assert probe["source_project_id"] == pid
    assert probe["source_slug"] == "smoke-probe"
    assert probe["validation_issues"] == []
    assert probe["ran_run_once"] is True
    assert probe["run_count"] == 1
    assert probe["last_error"] is None
    # sandbox 应已被 cleanup（DB 不应留 sandbox- 项目）
    rows = await db_session.execute(
        select(Mission).where(Mission.slug.like("sandbox-smoke-probe-%"))
    )
    assert rows.scalars().all() == []

    # judge：测试环境无 LLM provider → needs_review
    assert "verdict" in judge


async def test_smoke_test_unknown_project(
    seeded_client: AsyncClient, db_session: AsyncSession
) -> None:
    """unknown mission_id → ValueError"""
    auth = await _auth(seeded_client)
    await _bootstrap_project(seeded_client, auth)  # ensure DB ready

    bogus = uuid.UUID("00000000-0000-0000-0000-000000000001")
    with pytest.raises(ValueError):
        await mission_test_runner.run_smoke_test(db_session, bogus)


async def test_cleanup_sandbox_refuses_non_sandbox(
    seeded_client: AsyncClient, db_session: AsyncSession
) -> None:
    """cleanup_sandbox 必须拒绝非 sandbox- 项目（防误删）"""
    auth = await _auth(seeded_client)
    pid_str = await _bootstrap_project(seeded_client, auth)
    with pytest.raises(ValueError, match="sandbox"):
        await mission_test_runner.cleanup_sandbox(db_session, uuid.UUID(pid_str))
