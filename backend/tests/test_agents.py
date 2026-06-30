"""Phase 4 Agent API 测试。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.db.init_db import seed_builtin_skills

pytestmark = pytest.mark.asyncio


async def _auth(client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _bootstrap_model(client: AsyncClient, auth: dict[str, str]) -> str:
    """创建 provider + sync models，返回第一个 chat 模型 id。"""
    p = await client.post(
        "/api/providers",
        headers=auth,
        json={"name": "openai-for-agent", "provider_type": "openai", "api_key": "sk-x"},
    )
    await client.post(f"/api/providers/{p.json()['id']}/sync-models", headers=auth)
    models = (await client.get(f"/api/providers/{p.json()['id']}/models", headers=auth)).json()
    chat = next(m for m in models if m["model_type"] == "chat")
    return chat["id"]


async def test_create_and_get_agent(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    model_id = await _bootstrap_model(seeded_client, auth)

    resp = await seeded_client.post(
        "/api/agents",
        headers=auth,
        json={
            "name": "Supervisor",
            "description": "工作流主管",
            "model_id": model_id,
            "soul_md": "你是专业的项目主管。",
            "protocol_md": "对话协议：用户输入 → 规划 → 下发任务。",
            "domain_memory_md": "",
            "max_iterations": 15,
            "temperature": 0.5,
        },
    )
    assert resp.status_code == 201, resp.text
    agent = resp.json()
    assert agent["name"] == "Supervisor"
    # seeded_db 里没 seed 内置 Skill，因此自动绑定命中 0 个
    assert agent["skill_bindings"] == []
    assert agent["mcp_bindings"] == []

    # 同名冲突
    dup = await seeded_client.post(
        "/api/agents",
        headers=auth,
        json={"name": "Supervisor", "model_id": model_id},
    )
    assert dup.status_code == 409

    # GET
    got = await seeded_client.get(f"/api/agents/{agent['id']}", headers=auth)
    assert got.status_code == 200
    assert got.json()["max_iterations"] == 15


async def test_create_agent_invalid_model(seeded_client: AsyncClient) -> None:
    auth = await _auth(seeded_client)
    import uuid as _uuid

    resp = await seeded_client.post(
        "/api/agents",
        headers=auth,
        json={"name": "bad", "model_id": str(_uuid.uuid4())},
    )
    assert resp.status_code == 400


async def test_bind_skill_and_mcp(seeded_client: AsyncClient, seeded_db) -> None:
    await seed_builtin_skills(seeded_db)
    auth = await _auth(seeded_client)
    model_id = await _bootstrap_model(seeded_client, auth)

    agent = (
        await seeded_client.post(
            "/api/agents",
            headers=auth,
            # kind='worker' 才会按 worker/all scope 自动绑定（不传 kind 会落 utility，只绑 all）
            json={"name": "WorkerA", "model_id": model_id, "kind": "worker"},
        )
    ).json()

    # R2-4/V7.5 · 新建 worker Agent 时应按 SkillScope 自动绑定：worker/all scope，不绑 super-only
    all_skills = (await seeded_client.get("/api/skills", headers=auth)).json()
    bound_slugs = {
        next(s["slug"] for s in all_skills if s["id"] == b["skill_id"])
        for b in agent["skill_bindings"]
    }
    # super-only dispatch 工具不应绑到 worker（scope='super'）
    _SUPER_ONLY = {"invoke_worker", "invoke_workers_parallel", "list_workers",
                   "request_new_capability", "request_approval", "request_structured_input"}
    for excluded in _SUPER_ONLY:
        assert excluded not in bound_slugs, f"{excluded} (super-only) 不应绑到 worker"
    initial_count = len(agent["skill_bindings"])

    # workspace_write 已经在自动绑定里；再次 POST 相当于 upsert，总数不变
    ws_write = next(s for s in all_skills if s["slug"] == "workspace_write")
    bind = await seeded_client.post(
        f"/api/agents/{agent['id']}/skills/{ws_write['id']}", headers=auth
    )
    assert bind.status_code == 200
    assert bind.json()["skill_id"] == ws_write["id"]

    # 读取详情：自动绑定数量保持不变
    detail = (await seeded_client.get(f"/api/agents/{agent['id']}", headers=auth)).json()
    assert len(detail["skill_bindings"]) == initial_count

    # 绑定 MCP
    mcp = (
        await seeded_client.post(
            "/api/mcp-servers",
            headers=auth,
            json={"name": "fs-agent", "server_type": "stdio", "command": ["echo"]},
        )
    ).json()
    bind_mcp = await seeded_client.post(
        f"/api/agents/{agent['id']}/mcp-servers/{mcp['id']}", headers=auth
    )
    assert bind_mcp.status_code == 200

    # 解绑 Skill
    dele = await seeded_client.delete(
        f"/api/agents/{agent['id']}/skills/{ws_write['id']}", headers=auth
    )
    assert dele.status_code == 204


async def test_agent_test_endpoint(seeded_client: AsyncClient, seeded_db) -> None:
    await seed_builtin_skills(seeded_db)
    auth = await _auth(seeded_client)
    model_id = await _bootstrap_model(seeded_client, auth)

    agent = (
        await seeded_client.post(
            "/api/agents",
            headers=auth,
            json={
                "name": "TestAgent",
                "model_id": model_id,
                "soul_md": "你是测试助手。",
            },
        )
    ).json()

    # 新建时已自动绑定所有内置 Skill（除 Supervisor 专用），这里直接走 test endpoint
    test = await seeded_client.post(
        f"/api/agents/{agent['id']}/test",
        headers=auth,
        json={"input": "分析需求"},
    )
    assert test.status_code == 200, test.text
    payload = test.json()
    assert payload["ok"] is True
    # R2-4/V7.5 · 自动绑定走 SkillScope（worker/all），不再按固定黑名单计数。
    # 只断言确实绑了工具（>0）且没绑 super-only。
    assert payload["tools_loaded"] > 0


async def test_delete_agent_cascades_bindings(seeded_client: AsyncClient, seeded_db) -> None:
    await seed_builtin_skills(seeded_db)
    auth = await _auth(seeded_client)
    model_id = await _bootstrap_model(seeded_client, auth)
    agent = (
        await seeded_client.post(
            "/api/agents", headers=auth, json={"name": "Tmp", "model_id": model_id}
        )
    ).json()
    skills = (await seeded_client.get("/api/skills", headers=auth)).json()
    await seeded_client.post(f"/api/agents/{agent['id']}/skills/{skills[0]['id']}", headers=auth)
    dele = await seeded_client.delete(f"/api/agents/{agent['id']}", headers=auth)
    assert dele.status_code == 204
    miss = await seeded_client.get(f"/api/agents/{agent['id']}", headers=auth)
    assert miss.status_code == 404


async def test_delete_super_supervising_mission_returns_409_not_500(
    seeded_client: AsyncClient, seeded_db
) -> None:
    """删一个仍监管 mission 的 super → 友好 409，不是 FK RESTRICT 裸抛的 500。

    missions.supervisor_agent_id 的 FK 是 ondelete=RESTRICT；删除路径原本只查
    mission_nodes（worker 引用），漏查 supervisor_agent_id（super 引用）→ 删带运营实例的
    super 会 500。这里断言改成可读的 409 拦截。
    """
    import uuid as _uuid
    from sqlalchemy import select as _select
    from app.models.agent import Agent
    from app.models.user import User
    from app.domain.builder.factory import spawn_mission

    auth = await _auth(seeded_client)
    sid = _uuid.uuid4()
    seeded_db.add(Agent(
        id=sid, name=f"sup_{sid.hex[:6]}", slug=f"sup-{sid.hex[:6]}",
        display_name="Del Super", kind="super", category="custom",
        model_id=_uuid.uuid4(), soul_md="", protocol_md="",
    ))
    await seeded_db.commit()
    admin = (await seeded_db.execute(
        _select(User).where(User.username == "admin")
    )).scalar_one()
    await spawn_mission(
        seeded_db, super_agent_id=sid, name="带运营实例的 super",
        created_by=admin.id,
    )

    dele = await seeded_client.delete(f"/api/agents/{sid}", headers=auth)
    assert dele.status_code == 409, dele.text
    # 仍存在（未被误删）
    still = await seeded_client.get(f"/api/agents/{sid}", headers=auth)
    assert still.status_code == 200


async def test_delete_super_cascade_deletes_missions_keeps_global_workers(
    seeded_client: AsyncClient, seeded_db
) -> None:
    """ADR-027 · ?cascade=true：删 super → 连带删其所有 Mission；worker 是平台级共享资源
    （按 capability 全局发现，不再按 mission 预绑），不级联删 —— 全部保留。"""
    import uuid as _uuid
    from sqlalchemy import select as _select
    from app.models.agent import Agent
    from app.models.user import User
    from app.domain.builder.factory import spawn_mission

    auth = await _auth(seeded_client)
    admin = (await seeded_db.execute(
        _select(User).where(User.username == "admin")
    )).scalar_one()

    sid = _uuid.uuid4()
    wid = _uuid.uuid4()        # 平台 worker → ADR-027 不级联删
    sys_wid = _uuid.uuid4()    # 系统 worker → 保留
    seeded_db.add_all([
        Agent(id=sid, name=f"sup_{sid.hex[:6]}", slug=f"sup-{sid.hex[:6]}",
              kind="super", category="custom", model_id=_uuid.uuid4(), soul_md="", protocol_md=""),
        Agent(id=wid, name=f"w_{wid.hex[:6]}", kind="worker", capability="x_ops",
              category="worker.custom", model_id=_uuid.uuid4(), soul_md="", protocol_md=""),
        Agent(id=sys_wid, name=f"w_sys_{sys_wid.hex[:6]}", kind="worker", capability="sys_ops",
              category="worker.custom", model_id=_uuid.uuid4(), soul_md="", protocol_md="",
              is_system=True),
    ])
    await seeded_db.commit()

    await spawn_mission(seeded_db, super_agent_id=sid, name="m1", created_by=admin.id)

    dele = await seeded_client.delete(f"/api/agents/{sid}?cascade=true", headers=auth)
    assert dele.status_code == 200, dele.text

    # super 没了；worker 都还在（平台级共享，不级联删）
    assert (await seeded_client.get(f"/api/agents/{sid}", headers=auth)).status_code == 404
    assert await seeded_db.get(Agent, wid) is not None, "平台 worker 不应被级联删"
    assert await seeded_db.get(Agent, sys_wid) is not None


async def _mk_super_with_mission(seeded_db):
    """建：super A(带 mission mA) + 一个平台 worker。返回 (sidA, wid)。"""
    import uuid as _uuid
    from sqlalchemy import select as _select
    from app.models.agent import Agent
    from app.models.user import User
    from app.domain.builder.factory import spawn_mission

    admin = (await seeded_db.execute(_select(User).where(User.username == "admin"))).scalar_one()
    sidA = _uuid.uuid4()
    wid = _uuid.uuid4()
    seeded_db.add_all([
        Agent(id=sidA, name=f"A_{sidA.hex[:6]}", slug=f"a-{sidA.hex[:6]}", kind="super",
              category="custom", model_id=_uuid.uuid4(), soul_md="", protocol_md=""),
        Agent(id=wid, name=f"w_{wid.hex[:6]}", kind="worker", capability="e_ops",
              category="worker.custom", model_id=_uuid.uuid4(), soul_md="", protocol_md=""),
    ])
    await seeded_db.commit()
    await spawn_mission(seeded_db, super_agent_id=sidA, name="mA", created_by=admin.id)
    return sidA, wid


async def test_cascade_delete_keeps_global_workers(
    seeded_client: AsyncClient, seeded_db
) -> None:
    """ADR-027 · 级联删 super A → mission 删除；平台 worker 全部保留（无 mission 所属关系）。"""
    from app.models.agent import Agent
    auth = await _auth(seeded_client)
    sidA, wid = await _mk_super_with_mission(seeded_db)

    dele = await seeded_client.delete(f"/api/agents/{sidA}?cascade=true", headers=auth)
    assert dele.status_code == 200, dele.text
    assert await seeded_db.get(Agent, wid) is not None, "平台 worker 不应被级联删"


async def test_cascade_preview_reports_missions_no_worker_deletion(
    seeded_client: AsyncClient, seeded_db
) -> None:
    """ADR-027 · GET /cascade-preview：报告会删的 mission；worker 不再被级联删 → 列表恒为空。"""
    auth = await _auth(seeded_client)
    sidA, _wid = await _mk_super_with_mission(seeded_db)

    resp = await seeded_client.get(f"/api/agents/{sidA}/cascade-preview", headers=auth)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mission_count"] == 1
    assert data["workers_to_delete"] == [], data
    assert data["workers_to_keep"] == [], data
