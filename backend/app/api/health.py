"""健康检查端点。"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.deps import DBSession

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    """基础存活检查（不依赖 DB）。"""
    return {"status": "ok"}


@router.get("/db")
async def health_db(db: DBSession) -> dict[str, str]:
    """数据库连通性检查。"""
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
