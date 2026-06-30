"""ADR-019(修订) · OnboardingGate 只认 LLM —— 语言不再阻塞安装（语言是 per-user UILanguage）。"""
from __future__ import annotations

import pytest

from app.db.init_db import _is_platform_installed
from app.domain.onboarding import default_model as _dm
from app.domain.onboarding import seed_language as _sl

pytestmark = pytest.mark.asyncio


class _FakeModel:
    pass


async def test_installed_iff_default_model(db_session, monkeypatch):
    async def _has(db, role):  # noqa: ANN001
        return _FakeModel()

    monkeypatch.setattr(_dm, "resolve_default_model", _has)
    assert await _is_platform_installed(db_session) is True


async def test_not_installed_without_model(db_session, monkeypatch):
    async def _none(db, role):  # noqa: ANN001
        return None

    monkeypatch.setattr(_dm, "resolve_default_model", _none)
    assert await _is_platform_installed(db_session) is False


def test_is_supported_language():
    assert _sl.is_supported_language("en")
    assert _sl.is_supported_language("zh")
    assert not _sl.is_supported_language("fr")
    assert not _sl.is_supported_language(None)


async def test_get_seed_language_defaults_en(db_session):
    # 未设 system_settings（sqlite 无表）→ 回退 'en'（非 gate 故有默认）
    assert await _sl.get_seed_language(db_session) == "en"
