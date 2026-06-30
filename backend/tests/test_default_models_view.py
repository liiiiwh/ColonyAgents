"""ADR-016 / 续接① · 默认模型「可见性」：把 supervisor/agent/embedding 三个默认模型
解析成带来源(system_settings|env)+ provider/model_id 展示名的视图，供设置页显示&编辑。

为什么需要：env-install 路径只把默认模型写在 .env（DEFAULT_*_MODEL_ID），从不回写
system_settings，导致设置页（读 system_settings）看不到。describe_default_models 统一
按 system_settings>env 解析出「有效值 + 来源」，设置页据此始终能显示真实生效的默认模型。
"""
import pytest_asyncio

from app.core import system_settings as _ss
from app.core.config import settings
from app.domain.onboarding.default_model import describe_default_models
from app.models.provider import LLMModel, LLMProvider


@pytest_asyncio.fixture
async def seeded_model(db_session):
    prov = LLMProvider(name="prov", provider_type="openai", api_key="enc")
    db_session.add(prov)
    await db_session.flush()
    m = LLMModel(provider_id=prov.id, model_id="m1", display_name="M1")
    db_session.add(m)
    await db_session.commit()
    return prov, m


def _patch_ss(monkeypatch, overrides: dict):
    async def fake_get(db, key, default=None):
        return overrides.get(key, default)
    monkeypatch.setattr(_ss, "get", fake_get)


async def test_env_only_supervisor_shows_env_source_and_label(db_session, seeded_model, monkeypatch):
    _, m = seeded_model
    _patch_ss(monkeypatch, {})
    monkeypatch.setattr(settings, "DEFAULT_SUPERVISOR_MODEL_ID", "prov/m1")
    monkeypatch.setattr(settings, "DEFAULT_AGENT_MODEL_ID", None)
    rows = {r["role"]: r for r in await describe_default_models(db_session)}
    sup = rows["supervisor"]
    assert sup["source"] == "env"
    assert sup["model_id"] == str(m.id)
    assert sup["label"] == "prov/m1"  # provider/model_id 展示，绝不裸 uuid
    # 三个 role 都在
    assert set(rows) == {"supervisor", "agent", "embedding"}


async def test_system_settings_embedding_wins_and_marks_source(db_session, seeded_model, monkeypatch):
    _, m = seeded_model
    _patch_ss(monkeypatch, {"default_embedding_model_id": "prov/m1"})
    rows = {r["role"]: r for r in await describe_default_models(db_session)}
    emb = rows["embedding"]
    assert emb["source"] == "system_settings"
    assert emb["model_id"] == str(m.id)
    assert emb["label"] == "prov/m1"


async def test_unset_role_reports_none(db_session, monkeypatch):
    _patch_ss(monkeypatch, {})
    monkeypatch.setattr(settings, "DEFAULT_AGENT_MODEL_ID", None)
    rows = {r["role"]: r for r in await describe_default_models(db_session)}
    assert rows["agent"]["source"] == "none"
    assert rows["agent"]["model_id"] is None
    assert rows["agent"]["label"] is None
