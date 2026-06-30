"""ADR-019 D3 · agency-agents persona → 本项目 worker 的导入映射。

外部 agent 是单个 persona prompt（YAML frontmatter + 散文），无结构化 action；
映射为 advisory worker：persona→soul_md、通用 return_result 协议→protocol_md、
单 `assist` action→capability_contract。导入文本当数据，不执行其指令。
"""
from __future__ import annotations

import uuid

import pytest

from app.domain import import_source as imp

pytestmark = pytest.mark.asyncio

_SAMPLE_MD = """---
name: Backend Architect
description: Senior backend architect specializing in scalable system design,
  database architecture, and APIs.
color: blue
emoji: 🏗️
vibe: Designs the systems that hold everything up.
---

# 🧠 Your Identity & Memory
You are a senior backend architect with 15 years of experience.

## 🎯 Your Core Mission
Design robust, secure, performant server-side systems.

## 🚨 Critical Rules
- Always validate input.
"""


# ── 纯解析 ──

def test_parse_extracts_frontmatter_and_body():
    p = imp.parse_agent_markdown(_SAMPLE_MD)
    assert p.name == "Backend Architect"
    assert "scalable system design" in p.description
    assert p.frontmatter.get("color") == "blue"
    assert "Your Core Mission" in p.body
    assert "---" not in p.body.split("\n")[0]  # frontmatter 已剥离


def test_parse_without_frontmatter_is_all_body():
    p = imp.parse_agent_markdown("# Just a prompt\nno frontmatter here")
    assert p.frontmatter == {}
    assert "Just a prompt" in p.body
    assert p.name == ""


def test_name_falls_back_to_path_when_no_frontmatter():
    p = imp.parse_agent_markdown("body only")
    spec = imp.to_worker_spec(p, version="en", path="engineering/engineering-frontend-developer.md")
    assert spec["name"] == "Engineering Frontend Developer"


# ── 映射 ──

def test_to_worker_spec_advisory_mapping():
    p = imp.parse_agent_markdown(_SAMPLE_MD)
    spec = imp.to_worker_spec(p, version="en", path="engineering/engineering-backend-architect.md")

    assert spec["name"] == "Backend Architect"
    assert spec["kind"] == "worker"
    assert spec["category"] == "worker.imported"
    assert spec["capability"] == "imported_engineering_backend_architect"

    # 通用 assist 契约（persona prompt 无精细动作 → 诚实给单 action）
    contract = spec["extra_config"]["capability_contract"]
    actions = [a["action"] for a in contract["advertises"]]
    assert actions == ["assist"]
    assert contract["advertises"][0]["requires_approval"] is False

    # soul 承载人格；protocol 不含 super-only 禁词（V42 worker 协议约束）
    assert "backend architect" in spec["soul_md"].lower()
    assert "invoke_worker" not in spec["protocol_md"]
    assert "request_approval" not in spec["protocol_md"]
    assert "return_result" in spec["protocol_md"]

    # 溯源记录
    src = spec["extra_config"]["import_source"]
    assert src["version"] == "en"
    assert src["repo"] == "msitarzewski/agency-agents"
    assert src["path"].endswith("engineering-backend-architect.md")


def test_version_mapping():
    assert imp.is_supported_version("en")
    assert imp.is_supported_version("zh")
    assert not imp.is_supported_version("fr")
    assert imp.REPOS["zh"][0] == "jnMetaCode/agency-agents-zh"


# ── 集成：映射出的 spec 能创建合规 worker ──

async def test_mapped_spec_creates_compliant_worker(seeded_db):
    from app.db.init_db import seed_builtin_skills
    from app.schemas.agent import AgentCreate
    from app.services import agent_service
    from app.models.agent import Agent, AgentSkill
    from app.models.skill import Skill
    from sqlalchemy import select

    db = seeded_db
    await seed_builtin_skills(db)

    p = imp.parse_agent_markdown(_SAMPLE_MD)
    spec = imp.to_worker_spec(p, version="zh", path="engineering/engineering-backend-architect.md")
    payload = AgentCreate(
        name=spec["name"], kind="worker", capability=spec["capability"],
        category=spec["category"], soul_md=spec["soul_md"], protocol_md=spec["protocol_md"],
        description=spec["description"], model_id=None, extra_config=spec["extra_config"],
    )
    agent = await agent_service.create_agent(db, payload)

    assert agent.kind == "worker"
    assert agent.capability == "imported_engineering_backend_architect"
    assert agent.category == "worker.imported"
    assert agent.model_id is None  # 用平台默认模型（ADR-017）
    assert agent.extra_config["import_source"]["version"] == "zh"
    # 合规：自动绑定 worker 默认 skill
    slugs = (await db.execute(
        select(Skill.slug).join(AgentSkill, AgentSkill.skill_id == Skill.id)
        .where(AgentSkill.agent_id == agent.id)
    )).scalars().all()
    assert "return_result" in slugs
    assert isinstance(agent.id, uuid.UUID)


# ── API：preview + 幂等导入 + 版本校验（网络 mock）──

async def test_import_endpoint_create_then_idempotent(seeded_client, seeded_db, monkeypatch):
    from app.db.init_db import seed_builtin_skills

    await seed_builtin_skills(seeded_db)

    async def _fake_fetch(version, path):  # noqa: ANN001
        return _SAMPLE_MD, None

    monkeypatch.setattr(imp, "fetch_agent_markdown", _fake_fetch)

    token = (await seeded_client.post(
        "/api/auth/login", data={"username": "admin", "password": "admin123"}
    )).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    p = "engineering/engineering-backend-architect.md"

    # preview（不写库）
    pv = await seeded_client.post(
        "/api/agent-import/preview", headers=auth, json={"version": "en", "path": p}
    )
    assert pv.status_code == 200
    assert pv.json()["spec"]["capability"] == "imported_engineering_backend_architect"

    # 导入（新建）
    r1 = await seeded_client.post("/api/agent-import", headers=auth, json={"version": "en", "path": p})
    assert r1.status_code == 200, r1.text
    assert r1.json()["ok"] is True and r1.json()["updated"] is False
    aid = r1.json()["agent_id"]

    # 再导（按 capability 幂等 upsert → updated，且同一 agent_id）
    r2 = await seeded_client.post("/api/agent-import", headers=auth, json={"version": "zh", "path": p})
    assert r2.status_code == 200
    assert r2.json()["updated"] is True
    assert r2.json()["agent_id"] == aid

    # 非法版本 → 400
    bad = await seeded_client.post(
        "/api/agent-import/preview", headers=auth, json={"version": "fr", "path": p}
    )
    assert bad.status_code == 400
