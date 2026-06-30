"""V7.5 · conftest 修复 · 全部 model 能在 sqlite 建表（解锁集成测试）。

之前 agent_protocol_history.metrics_baseline 用 raw postgresql.JSONB → sqlite 'visit_JSONB' AttributeError
→ Base.metadata.create_all 整个炸 → 88 个集成测试 setup error。
修：JSONB 改 cross-dialect（JSON().with_variant(JSONB,'postgresql')），sqlite 回落 JSON。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.base_all import *  # noqa: F401,F403 — 注册所有模型到 metadata


@pytest.mark.asyncio
async def test_full_metadata_create_all_on_sqlite():
    """全 Base.metadata 在 sqlite 建表不抛（含 agent_protocol_history / knowledge embedding）。"""

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        # 不应抛 'visit_JSONB' AttributeError
        await conn.run_sync(Base.metadata.create_all)
    # 关键表都建出来了
    names = set(Base.metadata.tables.keys())
    assert "agent_protocol_history" in names
    assert "agents" in names
    await engine.dispose()
