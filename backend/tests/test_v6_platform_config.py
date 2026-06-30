"""R3-6 · 类型化 PlatformConfig · 消灭 14 个 magic-string config key。

之前：散在 6 文件的 `get_int(db, "worker.max_clarification_rounds", 3)`；key 拼错静默落 default，
default 在各 caller 间可能分歧。现在：集中 dataclass + 一次 load + 属性访问（IDE 补全 + typo 编译挂）。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


from sqlalchemy import text as _sql_text


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # system_settings 表（raw SQL；该表无 ORM model）
    async with engine.begin() as conn:
        await conn.execute(_sql_text(
            "CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT)"
        ))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_load_returns_defaults_when_db_empty(db_session):
    """DB 没配任何 key → 全部用 dataclass 默认值（不抛错）。"""
    from app.core.platform_config import PlatformConfig
    cfg = await PlatformConfig.load(db_session)
    assert cfg.worker_max_clarification_rounds == 3   # V37
    assert cfg.invoke_worker_max_nesting_depth == 2   # V17
    assert cfg.invoke_worker_timeout_seconds == 600
    assert cfg.super_max_pending_msgs_per_super == 20
    assert cfg.super_auto_trigger_on_user_msg is True
    assert cfg.live_events_enabled is True


@pytest.mark.asyncio
async def test_db_value_overrides_default(db_session):
    """DB 里配了 key → 覆盖 default。"""
    from app.core import system_settings

    await db_session.execute(_sql_text(
        "INSERT INTO system_settings (key, value) VALUES ('worker.max_clarification_rounds', '7')"
    ))
    await db_session.commit()
    system_settings.invalidate()

    from app.core.platform_config import PlatformConfig
    cfg = await PlatformConfig.load(db_session)
    assert cfg.worker_max_clarification_rounds == 7


@pytest.mark.asyncio
async def test_typed_fields_have_correct_python_types(db_session):
    from app.core.platform_config import PlatformConfig
    cfg = await PlatformConfig.load(db_session)
    assert isinstance(cfg.invoke_worker_timeout_seconds, int)
    assert isinstance(cfg.super_user_chat_cancel_timeout_seconds, float)
    assert isinstance(cfg.super_auto_trigger_on_user_msg, bool)
