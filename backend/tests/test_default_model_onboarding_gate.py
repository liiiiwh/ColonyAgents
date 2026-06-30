"""Onboarding gate：默认模型必须由用户在 UI 显式选，不能被 config 写死的 deepseek 默认顶掉。

真 bug（用户 fresh install 实测）：config 把 DEFAULT_SUPERVISOR/AGENT_MODEL_ID 写死成
`deepseek/deepseek-v4-pro`。用户一加 deepseek provider，`_is_platform_installed`（=supervisor
默认模型可解析）就因这条 env 默认变 True → onboarding 的「选默认模型」步骤被跳过、引导不弹。
这与 ADR-016「把选默认模型从 env 写死搬到 UI」矛盾。

修复：config 默认改空 → 没 .env 覆盖、没 UI 显式选时 supervisor 解析为 None → 平台视为未安装
→ onboarding 弹模型选择。部署者仍可在真实 .env 里预设 DEFAULT_*_MODEL_ID 走无人值守。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text as _sql_text

from app.core import system_settings as _ss
from app.core.config import Settings, settings
from app.db.init_db import _is_platform_installed
from app.models.provider import LLMModel, LLMProvider

pytestmark = pytest.mark.asyncio


def test_config_default_models_empty_by_default():
    """config 不再写死 deepseek：OSS 用户开箱不应被静默塞默认模型（ADR-016）。"""
    assert Settings.model_fields["DEFAULT_SUPERVISOR_MODEL_ID"].default == ""
    assert Settings.model_fields["DEFAULT_AGENT_MODEL_ID"].default == ""


async def _seed_deepseek(db) -> uuid.UUID:
    prov = LLMProvider(name="deepseek", provider_type="openai", api_key="enc")
    db.add(prov)
    await db.flush()
    m = LLMModel(provider_id=prov.id, model_id="deepseek-v4-pro",
                 display_name="dsv4", model_type="chat", is_enabled=True)
    db.add(m)
    await db.commit()
    return m.id


async def test_not_installed_without_explicit_default(db_session, monkeypatch):
    """空 env 默认 + 未在 UI 选 + 即便存在 deepseek-v4-pro 模型 → 平台未安装（应弹 onboarding）。"""
    monkeypatch.setattr(settings, "DEFAULT_SUPERVISOR_MODEL_ID", "")
    monkeypatch.setattr(settings, "DEFAULT_AGENT_MODEL_ID", "")
    _ss.invalidate()
    await _seed_deepseek(db_session)
    assert await _is_platform_installed(db_session) is False


async def test_installed_after_explicit_ui_choice(db_session, monkeypatch):
    """用户在 UI 显式选了默认 supervisor 模型（写 system_settings）→ 平台视为已安装。"""
    monkeypatch.setattr(settings, "DEFAULT_SUPERVISOR_MODEL_ID", "")
    monkeypatch.setattr(settings, "DEFAULT_AGENT_MODEL_ID", "")
    mid = await _seed_deepseek(db_session)
    await db_session.execute(_sql_text(
        "INSERT INTO system_settings (key, value) VALUES ('default_supervisor_model_id', :v)"
    ), {"v": str(mid)})
    await db_session.commit()
    _ss.invalidate()
    assert await _is_platform_installed(db_session) is True
