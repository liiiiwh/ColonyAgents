"""Phase 6 Session / Branch / Chat SSE 测试。"""

from __future__ import annotations

import json
import uuid as _uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _auth(client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _user_auth(
    client: AsyncClient, username: str, password: str = "pass1234"
) -> dict[str, str]:
    resp = await client.post("/api/auth/login", data={"username": username, "password": password})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_user(
    client: AsyncClient,
    auth: dict[str, str],
    *,
    username: str,
    email: str,
    role: str = "user",
) -> dict:
    resp = await client.post(
        "/api/users",
        headers=auth,
        json={
            "username": username,
            "email": email,
            "password": "pass1234",
            "role": role,
            "is_active": True,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _make_active_project(
    client: AsyncClient,
    auth: dict[str, str],
    *,
    slug: str = "chat-test",
    name: str = "ChatTest",
    node_names: tuple[str, ...] = ("parse", "generate", "verify"),
) -> dict[str, str]:
    p = await client.post(
        "/api/providers",
        headers=auth,
        json={"name": "prov-session", "provider_type": "openai", "api_key": "sk-x"},
    )
    pid = p.json()["id"]
    await client.post(f"/api/providers/{pid}/sync-models", headers=auth)
    models = (await client.get(f"/api/providers/{pid}/models", headers=auth)).json()
    chat = next(m for m in models if m["model_type"] == "chat")
    sup = await client.post(
        "/api/agents", headers=auth, json={"name": "Sup", "model_id": chat["id"]}
    )
    wrk = await client.post(
        "/api/agents", headers=auth, json={"name": "Wrk", "model_id": chat["id"]}
    )
    proj = await client.post(
        "/api/missions/full",
        headers=auth,
        json={
            "name": name,
            "slug": slug,
            "supervisor_agent_id": sup.json()["id"],
        },
    )
    proj_id = proj.json()["id"]
    # 添加测试节点（默认 parse / generate / verify）
    for i, node_name in enumerate(node_names):
        await client.post(
            f"/api/missions/{proj_id}/nodes",
            headers=auth,
            json={"agent_id": wrk.json()["id"], "node_name": node_name, "node_order": i},
        )
    await client.post(f"/api/missions/{proj_id}/activate", headers=auth)
    return {"mission_id": proj_id, "slug": slug}


async def test_memory_read_write_per_branch_isolation(
    seeded_client: AsyncClient, db_session
) -> None:
    """验证 memory_read / memory_write 工具端到端（ADR-018 mission-only · 按 thread 隔离）：
    - 工具上下文含 mission_id + thread_key + agent_node_name 时可写入
    - 读回与写入一致
    - 跨 thread 隔离（thread A 写的记忆在 thread B 读不到）
    - Domain Memory（agent.domain_memory_md）作为初始模板，在 thread memory 写入后被完全覆盖
    """
    import uuid

    from app.services import agent_service, memory_service
    from app.skills_builtin.context import BuiltinToolContext
    from app.skills_builtin.worker_io.memory_skills import memory_read_tool, memory_write_tool

    auth = await _auth(seeded_client)
    info = await _make_active_project(seeded_client, auth)
    mission_id = uuid.UUID(info["mission_id"])

    # 构造两个同 mission、不同 thread_key 的 BuiltinToolContext
    from app.db.session import AsyncSessionLocal

    def _factory():
        return AsyncSessionLocal()

    ctx_a = BuiltinToolContext(
        mission_id=mission_id,
        thread_key="thread-a",
        agent_node_name="parse",
        db_factory=_factory,
    )
    ctx_b = BuiltinToolContext(
        mission_id=mission_id,
        thread_key="thread-b",
        agent_node_name="parse",
        db_factory=_factory,
    )

    read_a = memory_read_tool(ctx_a)
    write_a = memory_write_tool(ctx_a)
    read_b = memory_read_tool(ctx_b)
    write_b = memory_write_tool(ctx_b)

    # 初始：两 thread 均无记忆
    assert "尚无" in await read_a.ainvoke({})
    assert "尚无" in await read_b.ainvoke({})

    # 写 A
    ack = await write_a.ainvoke({"content": "threadA: 用户偏爱科幻风，避免 emoji。"})
    assert "已更新" in ack

    # 读 A 命中，读 B 仍无
    a_mem = await read_a.ainvoke({})
    assert "科幻风" in a_mem
    assert "尚无" in await read_b.ainvoke({})

    # 再写 B，独立于 A
    await write_b.ainvoke({"content": "threadB: 用户偏爱极简风。"})
    assert "极简风" in await read_b.ainvoke({})
    assert "科幻风" in await read_a.ainvoke({})  # A 不受影响

    # domain_memory_md 覆盖验证：
    # 在某个 agent 上设 domain_memory_md，当 branch memory 存在时 assemble_system_prompt_async 只用分支记忆
    from sqlalchemy import select

    from app.models.agent import Agent

    agent_row = (await db_session.execute(select(Agent).limit(1))).scalar_one()
    agent_row.domain_memory_md = "DOMAIN_SEED_TOKEN"
    await db_session.commit()
    await db_session.refresh(agent_row)
    prompt = await agent_service.assemble_system_prompt_async(db_session, agent_row, ctx_a)
    assert "科幻风" in prompt, "thread memory 必须被注入"
    assert "DOMAIN_SEED_TOKEN" not in prompt, "有 thread memory 时 domain seed 不应重复注入"

    # 换一个没写过 memory 的 ctx，此时 domain seed 应被注入
    empty_ctx = BuiltinToolContext(
        mission_id=mission_id,
        thread_key="thread-a",
        agent_node_name="never_written_node",
        db_factory=_factory,
    )
    empty_prompt = await agent_service.assemble_system_prompt_async(
        db_session, agent_row, empty_ctx
    )
    assert "DOMAIN_SEED_TOKEN" in empty_prompt

    # 清理：读回确认 compressed_message_count 默认为 0（ADR-018：ThreadAgentMemory 按 (mission, thread)）
    mem_a = await memory_service.get_thread_memory(db_session, mission_id, "thread-a", "parse")
    assert mem_a is not None
    assert mem_a.compressed_message_count == 0


