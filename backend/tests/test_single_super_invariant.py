"""单 super 不变量的 JSON 查询：extra_config 是通用 JSON 列（非 JSONB），
必须用 .as_string() 而非 .astext —— 后者在 generic JSON 上 AttributeError，会**静默拖垮 agent_create**
（实测：整个 BUILD 卡死、0 super）。本测试钉死这个查询表达式不再回归。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.agent import Agent

pytestmark = pytest.mark.asyncio


async def _seed_super(db, model_id, builder_session_id: str) -> uuid.UUID:
    aid = uuid.uuid4()
    db.add(Agent(
        id=aid, name=f"super-{builder_session_id[:6]}", model_id=model_id,
        kind="super", category="custom", soul_md="x", protocol_md="x",
        extra_config={"builder_session_id": builder_session_id},
    ))
    await db.commit()
    return aid


async def _seed_model(db) -> uuid.UUID:
    from app.models.provider import LLMProvider, LLMModel
    pid = uuid.uuid4()
    db.add(LLMProvider(id=pid, name="deepseek", provider_type="openai", api_key="x", base_url="https://x"))
    mid = uuid.uuid4()
    db.add(LLMModel(id=mid, provider_id=pid, model_id="deepseek-v4-pro",
                    display_name="deepseek-v4-pro", model_type="chat"))
    await db.commit()
    return mid


async def test_invariant_query_finds_existing_super(db_session):
    mid = await _seed_model(db_session)
    sid = str(uuid.uuid4())
    await _seed_super(db_session, mid, sid)
    # 这是 agent_create 单-super 不变量用的同一表达式
    found = (await db_session.execute(
        select(Agent).where(
            Agent.kind == "super",
            Agent.extra_config["builder_session_id"].as_string() == sid,
        )
    )).scalars().first()
    assert found is not None
    assert found.extra_config["builder_session_id"] == sid


async def test_invariant_query_no_match_for_other_session(db_session):
    mid = await _seed_model(db_session)
    await _seed_super(db_session, mid, str(uuid.uuid4()))
    other = (await db_session.execute(
        select(Agent).where(
            Agent.kind == "super",
            Agent.extra_config["builder_session_id"].as_string() == "no-such-session",
        )
    )).scalars().first()
    assert other is None
