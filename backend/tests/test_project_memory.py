"""M3: MissionAgentMemory + clear_memory + memory_scope 测试。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mission import Mission, MissionAgentMemory
from app.services import memory_service

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
    proj = (
        await client.post(
            "/api/missions/full",
            headers=auth,
            json={
                "name": "Mem Probe",
                "slug": "mem-probe",
                "supervisor_agent_id": sup.json()["id"],
            },
        )
    ).json()
    return proj["id"]


async def test_project_memory_upsert_and_get(
    seeded_client: AsyncClient, db_session: AsyncSession
) -> None:
    """直接走 memory_service.upsert_project_memory / get_project_memory。"""
    auth = await _auth(seeded_client)
    pid_str = await _bootstrap_project(seeded_client, auth)
    import uuid

    pid = uuid.UUID(pid_str)

    # 初始 None
    mem0 = await memory_service.get_project_memory(db_session, pid, "supervisor")
    assert mem0 is None

    # upsert 写入
    mem1 = await memory_service.upsert_project_memory(
        db_session, pid, "supervisor", memory_md="### v1", compressed_count=1
    )
    assert mem1.memory_md == "### v1"
    assert mem1.compressed_message_count == 1

    # upsert 更新 —— 现在是追加式：保留旧段 + 拼接新段，不再覆盖
    mem2 = await memory_service.upsert_project_memory(
        db_session, pid, "supervisor", memory_md="### v2", compressed_count=2
    )
    assert mem2.id == mem1.id  # 同一行
    assert "### v1" in mem2.memory_md  # 旧段保留
    assert "### v2" in mem2.memory_md  # 新段拼接
    assert "压缩段" in mem2.memory_md  # 段落 header
    assert mem2.compressed_message_count == 3  # 累加 1 + 2

    # 再 get 一遍
    mem3 = await memory_service.get_project_memory(db_session, pid, "supervisor")
    assert mem3 is not None
    assert "### v1" in mem3.memory_md
    assert "### v2" in mem3.memory_md


async def test_lifecycle_clear_memory(
    seeded_client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/missions/{id}/lifecycle/clear_memory 清空 project memory。"""
    auth = await _auth(seeded_client)
    pid_str = await _bootstrap_project(seeded_client, auth)
    import uuid

    pid = uuid.UUID(pid_str)

    # 种 3 行 memory
    for node in ("supervisor", "worker_a", "worker_b"):
        await memory_service.upsert_project_memory(
            db_session, pid, node, memory_md=f"## {node}", compressed_count=1
        )
    rows = (
        await db_session.execute(
            select(MissionAgentMemory).where(MissionAgentMemory.mission_id == pid)
        )
    ).scalars().all()
    assert len(rows) == 3

    # call API
    r = await seeded_client.post(
        f"/api/missions/{pid_str}/lifecycle/clear_memory", headers=auth
    )
    assert r.status_code == 200, r.text

    # 检查 DB
    rows_after = (
        await db_session.execute(
            select(MissionAgentMemory).where(MissionAgentMemory.mission_id == pid)
        )
    ).scalars().all()
    assert len(rows_after) == 0


async def test_clear_memory_unknown_project(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    bogus = "00000000-0000-0000-0000-000000000001"
    r = await seeded_client.post(
        f"/api/missions/{bogus}/lifecycle/clear_memory", headers=auth
    )
    assert r.status_code == 404


async def test_assemble_system_prompt_uses_project_memory(
    seeded_client: AsyncClient, db_session: AsyncSession
) -> None:
    """memory_scope='project' 时，assemble_system_prompt_async 应读 project memory。"""
    auth = await _auth(seeded_client)
    pid_str = await _bootstrap_project(seeded_client, auth)
    import uuid

    pid = uuid.UUID(pid_str)
    # 取出已创建的 supervisor agent
    proj = await db_session.get(Mission, pid)
    assert proj is not None
    from app.models.agent import Agent

    agent = await db_session.get(Agent, proj.supervisor_agent_id)
    assert agent is not None

    # 种一条 project memory
    await memory_service.upsert_project_memory(
        db_session, pid, "supervisor", memory_md="## 项目长期累计学到的事情", compressed_count=1
    )

    # 构造 BuiltinToolContext 走 project scope
    from app.services.agent_service import assemble_system_prompt_async
    from app.skills_builtin.context import BuiltinToolContext

    ctx = BuiltinToolContext(
        mission_id=pid,
        agent_node_name="supervisor",
        memory_scope="project",
    )
    prompt = await assemble_system_prompt_async(db_session, agent, ctx)
    assert "项目长期记忆" in prompt
    assert "项目长期累计学到的事情" in prompt
