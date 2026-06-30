"""_is_platform_installed = "a default supervisor model is configured" (ADR-017).

Platform agents are now seeded at boot regardless of LLM config, so "installed" no longer
means "the Builder project exists" — it means onboarding is done (a default model is set).
On a fresh DB with no default model it must return False (drives the onboarding modal) and
never raise (an earlier bug referenced Mission without importing it on this path).
"""
from __future__ import annotations

import pytest

from app.db.init_db import _is_platform_installed

pytestmark = pytest.mark.asyncio


async def test_returns_false_on_fresh_db_without_raising(db_session, monkeypatch):
    # No default model configured → not installed, no exception.
    monkeypatch.setattr("app.core.config.settings.DEFAULT_SUPERVISOR_MODEL_ID", "")
    monkeypatch.setattr("app.core.config.settings.DEFAULT_AGENT_MODEL_ID", "")
    result = await _is_platform_installed(db_session)
    assert result is False
