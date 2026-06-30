"""ADR-017 · agents resolve their model at runtime.

model_id=NULL means "use the platform default model" (by kind). _resolve_agent_model:
  - explicit model_id → that model
  - NULL + default configured → the default model
  - NULL + no default → raise LLMNotConfiguredError (agent exists but can't run)
"""
from __future__ import annotations

import uuid

import pytest

from app.models.agent import Agent
from app.models.provider import LLMModel, LLMProvider
from app.services.agent_service import LLMNotConfiguredError, _resolve_agent_model

pytestmark = pytest.mark.asyncio


async def _seed_model(db, model_id="deepseek-v4-pro") -> uuid.UUID:
    pid = uuid.uuid4()
    db.add(LLMProvider(id=pid, name="testprov", provider_type="openai", api_key="x", base_url="https://x"))
    mid = uuid.uuid4()
    db.add(LLMModel(id=mid, provider_id=pid, model_id=model_id, display_name=model_id,
                    model_type="chat", is_enabled=True))
    await db.commit()
    return mid


async def _mk_agent(db, *, model_id, kind="worker", name="a") -> Agent:
    a = Agent(name=name, category="custom", kind=kind, model_id=model_id, soul_md="x", protocol_md="x")
    db.add(a)
    await db.commit()
    return a


async def test_explicit_model_id_resolves(db_session):
    mid = await _seed_model(db_session)
    agent = await _mk_agent(db_session, model_id=mid, name="explicit")
    m = await _resolve_agent_model(db_session, agent)
    assert m.id == mid


async def test_null_model_uses_platform_default(db_session, monkeypatch):
    mid = await _seed_model(db_session, "deepseek-v4-pro")
    monkeypatch.setattr("app.core.config.settings.DEFAULT_AGENT_MODEL_ID", "deepseek-v4-pro")
    agent = await _mk_agent(db_session, model_id=None, name="dyn")
    m = await _resolve_agent_model(db_session, agent)
    assert m.id == mid


async def test_null_model_no_default_raises(db_session, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.DEFAULT_AGENT_MODEL_ID", "")
    monkeypatch.setattr("app.core.config.settings.DEFAULT_SUPERVISOR_MODEL_ID", "")
    agent = await _mk_agent(db_session, model_id=None, name="nollm")
    with pytest.raises(LLMNotConfiguredError):
        await _resolve_agent_model(db_session, agent)
