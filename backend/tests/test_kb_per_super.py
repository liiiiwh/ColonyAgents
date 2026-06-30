"""S7/ADR-023 · 知识库 per-super 共享。

同一 super 的多个 mission 共用一份 KB：_ensure_mission_kb 第二次复用不新建；
get_kb_by_project 自动路由到 super 共享 KB。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models.agent import Agent
from app.models.knowledge import KnowledgeBase
from app.models.mission import Mission
from app.models.provider import LLMModel, LLMProvider
from app.models.user import User
from app.services import knowledge_service
from app.services.mission_service import _ensure_mission_kb

pytestmark = pytest.mark.asyncio


async def _setup(db):
    u = User(username=f"u-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@t.io",
             hashed_password="x")
    db.add(u)
    prov = LLMProvider(name=f"p-{uuid.uuid4().hex[:5]}", provider_type="openai",
                       api_key="x", base_url="https://x")
    db.add(prov)
    await db.flush()
    emb = LLMModel(provider_id=prov.id, model_id="emb-1", display_name="Emb",
                   model_type="embedding", is_enabled=True)
    db.add(emb)
    sup = Agent(name=f"sup-{uuid.uuid4().hex[:6]}", category="custom", kind="super",
                model_id=None, soul_md="x", protocol_md="x")
    db.add(sup)
    await db.flush()
    m1 = Mission(name="m1", slug=f"m1-{uuid.uuid4().hex[:8]}", supervisor_agent_id=sup.id, created_by=u.id)
    m2 = Mission(name="m2", slug=f"m2-{uuid.uuid4().hex[:8]}", supervisor_agent_id=sup.id, created_by=u.id)
    db.add_all([m1, m2])
    await db.commit()
    for x in (u, sup, m1, m2):
        await db.refresh(x)
    return u, sup, m1, m2


async def test_kb_shared_across_missions_of_same_super(db_session):
    u, sup, m1, m2 = await _setup(db_session)
    await _ensure_mission_kb(db_session, m1, u.id)
    await _ensure_mission_kb(db_session, m2, u.id)  # same super → reuse

    cnt = (await db_session.execute(
        select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.super_agent_id == sup.id)
    )).scalar()
    assert cnt == 1, "同一 super 的两个 mission 应共用一份 KB"

    kb = await knowledge_service.get_kb_by_super(db_session, sup.id)
    assert kb is not None
    # builtin 自动路由：按 mission 取也命中 super 共享 KB
    routed = await knowledge_service.get_kb_by_project(db_session, m2.id)
    assert routed is not None and routed.id == kb.id
