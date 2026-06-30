"""ADR-016 · 默认模型解析：system_settings(UI 选) > env > None(fail loud 交调用方)。

把「选默认模型」从 env 写死搬到 UI，使任意 provider 的 OSS 用户都能开箱；
不静默替换模型（ADR-014）：无任何可解析默认 → 返回 None，调用方 fail loud。
"""
import uuid

import pytest
import pytest_asyncio

from app.core import system_settings as _ss
from app.core.config import settings
from app.domain.onboarding.default_model import resolve_default_model
from app.models.provider import LLMModel, LLMProvider


@pytest_asyncio.fixture
async def seeded_model(db_session):
    prov = LLMProvider(name="prov", provider_type="openai", api_key="enc")
    db_session.add(prov)
    await db_session.flush()
    m = LLMModel(provider_id=prov.id, model_id="m1", display_name="M1")
    db_session.add(m)
    await db_session.commit()
    return m


def _patch_ss(monkeypatch, overrides: dict):
    async def fake_get(db, key, default=None):
        return overrides.get(key, default)
    monkeypatch.setattr(_ss, "get", fake_get)


async def test_falls_back_to_env_when_no_override(db_session, seeded_model, monkeypatch):
    _patch_ss(monkeypatch, {})
    monkeypatch.setattr(settings, "DEFAULT_SUPERVISOR_MODEL_ID", "prov/m1")
    m = await resolve_default_model(db_session, "supervisor")
    assert m is not None and m.model_id == "m1"


async def test_system_settings_override_wins_over_env(db_session, seeded_model, monkeypatch):
    # env 指向一个解析不到的串；system_settings 指向真实 model id → 必须用 UI 选的
    _patch_ss(monkeypatch, {"default_supervisor_model_id": str(seeded_model.id)})
    monkeypatch.setattr(settings, "DEFAULT_SUPERVISOR_MODEL_ID", "ghost/nope")
    m = await resolve_default_model(db_session, "supervisor")
    assert m is not None and m.id == seeded_model.id


async def test_none_when_nothing_resolvable(db_session, seeded_model, monkeypatch):
    _patch_ss(monkeypatch, {})
    monkeypatch.setattr(settings, "DEFAULT_AGENT_MODEL_ID", "ghost/nope")
    m = await resolve_default_model(db_session, "agent")
    assert m is None
