"""异步 SQLAlchemy 引擎与 Session 工厂。

支持 PostgreSQL（生产）与 SQLite in-memory（测试）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import settings


def _build_engine_kwargs(database_url: str) -> dict[str, Any]:
    # echo 默认关：SQL echo（每条语句刷两行）太吵且会盖过真正的日志。需要逐句排查 SQL 时
    # 临时在 .env 设 DB_ECHO=true 单独开，不再绑定 DEBUG。
    kwargs: dict[str, Any] = {
        "echo": bool(getattr(settings, "DB_ECHO", False)),
        "pool_pre_ping": True,
    }
    if database_url.startswith("sqlite"):
        # in-memory sqlite 需 StaticPool + shared cache
        kwargs["poolclass"] = StaticPool
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = settings.DB_POOL_SIZE
        kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
        kwargs["pool_recycle"] = settings.DB_POOL_RECYCLE
    return kwargs


async_engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    **_build_engine_kwargs(settings.DATABASE_URL),
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
