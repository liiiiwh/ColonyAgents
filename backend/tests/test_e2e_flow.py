"""Phase 8 端到端 smoke 测试：串联所有核心流程。

1. 管理员登录
2. 配置 Provider + 同步模型
3. 查看 / 禁用内置 Skill
4. 创建自定义 instruction Skill
5. 创建 MCP Server 并测试
6. 创建 Supervisor Agent + 绑定 Skill
7. 创建 Worker Agent
8. 创建 Mission + 添加节点 + 激活
9. 创建 Session + SSE Chat
10. 触发回退创建 v2 分支
11. 切换回 v1 分支
12. 创建知识库 + 索引文档 + 检索
13. 存储：上传 / 下载 / 删除
"""

from __future__ import annotations

import uuid as _uuid

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


async def test_end_to_end_smoke(seeded_client: AsyncClient, seeded_db) -> None:
    from app.db.init_db import seed_builtin_skills

    await seed_builtin_skills(seeded_db)
    c = seeded_client

    # 1. 登录
    auth = {
        "Authorization": "Bearer "
        + (
            await c.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
        ).json()["access_token"]
    }
    me = await c.get("/api/auth/me", headers=auth)
    assert me.json()["role"] == "admin"

    # 2. Provider
    prov = (
        await c.post(
            "/api/providers",
            headers=auth,
            json={"name": "openai-e2e", "provider_type": "openai", "api_key": "sk-e2e"},
        )
    ).json()
    sync = await c.post(f"/api/providers/{prov['id']}/sync-models", headers=auth)
    assert sync.json()["synced"] >= 4
    models = (await c.get(f"/api/providers/{prov['id']}/models", headers=auth)).json()
    chat_model = next(m for m in models if m["model_type"] == "chat")
    embed_model = next(m for m in models if m["model_type"] == "embedding")

    # 3. Skills
    skills = (await c.get("/api/skills", headers=auth)).json()
    # M4 起：27 + 8 个 Builder skill = 35
    from app.skills_builtin.registry import BUILTIN_SKILL_METADATA
    assert len(skills) == len(BUILTIN_SKILL_METADATA)
    # 禁用 knowledge_index（示例）
    ki = next(s for s in skills if s["slug"] == "knowledge_index")
    r = await c.put(f"/api/skills/{ki['id']}", headers=auth, json={"is_enabled": False})
    assert r.status_code == 200

    # 4. 自定义 instruction Skill
    inst = await c.post(
        "/api/skills",
        headers=auth,
        json={
            "name": "E2E Soul",
            "slug": "e2e-soul",
            "skill_type": "instruction",
            "content_md": "你是测试 Supervisor。",
        },
    )
    assert inst.status_code == 201
    inst_id = inst.json()["id"]

    # 5. MCP Server
    mcp = await c.post(
        "/api/mcp-servers",
        headers=auth,
        json={"name": "e2e-fs", "server_type": "stdio", "command": ["echo", "noop"]},
    )
    assert mcp.status_code == 201
    mt = await c.post(f"/api/mcp-servers/{mcp.json()['id']}/test", headers=auth)
    assert mt.json()["reachable"] is True

    # 6. Supervisor Agent
    supervisor = await c.post(
        "/api/agents",
        headers=auth,
        json={
            "name": "E2E Supervisor",
            "model_id": chat_model["id"],
            "kind": "super",  # ADR-018 mission-only · /api/super/{slug}/chat 要求 supervisor 是 super
            "soul_md": "Supervisor soul",
            "protocol_md": "规划并分派任务",
        },
    )
    sup_id = supervisor.json()["id"]
    # 绑定 Skill（ADR-018 step5/X：set_branch_description 已删，改用 record_decision）
    ws_write = next(s for s in skills if s["slug"] == "workspace_write")
    rec_dec = next(s for s in skills if s["slug"] == "record_decision")
    await c.post(f"/api/agents/{sup_id}/skills/{ws_write['id']}", headers=auth)
    await c.post(f"/api/agents/{sup_id}/skills/{rec_dec['id']}", headers=auth)
    await c.post(f"/api/agents/{sup_id}/skills/{inst_id}", headers=auth)

    # 7. Worker Agent
    worker = await c.post(
        "/api/agents",
        headers=auth,
        json={"name": "E2E Worker", "model_id": chat_model["id"]},
    )
    wrk_id = worker.json()["id"]

    # Agent 单测
    test_resp = await c.post(f"/api/agents/{sup_id}/test", headers=auth, json={"input": "你好"})
    assert test_resp.json()["ok"] is True
    # R2-4/V7.5 · auto-bind 走 SkillScope（super/all），不再固定黑名单计数。
    # supervisor 应绑到 super-only 工具（invoke_worker 等）且 tools_loaded > 0。
    assert test_resp.json()["tools_loaded"] > 0

    # 8. Mission + Nodes + 激活
    proj = await c.post(
        "/api/missions/full",
        headers=auth,
        json={
            "name": "E2E Mission",
            "slug": "e2e",
            "supervisor_agent_id": sup_id,
        },
    )
    proj_id = proj.json()["id"]
    for i, name in enumerate(["analyze", "generate", "verify"]):
        await c.post(
            f"/api/missions/{proj_id}/nodes",
            headers=auth,
            json={"agent_id": wrk_id, "node_name": name, "node_order": i},
        )
    act = await c.post(f"/api/missions/{proj_id}/activate", headers=auth)
    assert act.json()["ok"] is True

    # 9. ADR-018 mission-only · 消息按 (mission_id=proj.id, thread_key='main') 写/读（直接走 service 层，
    #    不触发后台 daemon tick —— 带 LLM tick 的完整 chat e2e 在 docker 跑）。
    from app.services import messaging_service as _ss

    await _ss.append_message(seeded_db, _uuid.UUID(proj_id), "main", "user", "开始设计一款玩具")
    main_msgs = await _ss.list_thread_messages(seeded_db, _uuid.UUID(proj_id), "main")
    assert any(m.role == "user" and "玩具" in m.content for m in main_msgs)

    # 10-11. ADR-018 step5/X：rollback / activate branch e2e 步骤已删（rewind 废、分支实体退役）

    # 12. 知识库
    kb = await c.post(
        "/api/knowledge",
        headers=auth,
        json={
            "name": "E2E KB",
            "collection_name": "e2e_kb",
            "embedding_model_id": embed_model["id"],
        },
    )
    kb_id = kb.json()["id"]
    doc = await c.post(
        f"/api/knowledge/{kb_id}/documents",
        headers=auth,
        json={
            "filename": "materials.md",
            "content": "Colony 内置工具集涵盖 workspace、memory、knowledge、supervisor 等族。" * 8,
        },
    )
    assert doc.json()["status"] == "indexed"
    hits = await c.post(
        f"/api/knowledge/{kb_id}/search",
        headers=auth,
        json={"query": "材料", "top_k": 3},
    )
    assert len(hits.json()["hits"]) >= 1

    # 13. 存储
    up = await c.post(
        "/api/storage/upload",
        headers=auth,
        files={"file": ("artifact.txt", b"colony!", "text/plain")},
    )
    assert up.json()["key"] == "artifact.txt"
    lst = await c.get("/api/storage/files", headers=auth)
    assert any(o["key"] == "artifact.txt" for o in lst.json())
    dele = await c.delete("/api/storage/files", headers=auth, params={"key": "artifact.txt"})
    assert dele.status_code == 204

    # 全流程完成
