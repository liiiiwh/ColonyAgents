"""list_supers · v6.B · 给 super 查平台其它 super 候选。

Q7 mismatch 重定向流程依赖此函数：super LLM 收到不匹配 goal 后调
list_supers(keyword=goal_keywords) → 拿候选 → emit_redirect_suggestion。

不变式：
- 只返回 kind='super' AND is_enabled=True
- exclude_super_id 防止 super 给自己推荐自己
- keyword 走 name + description 模糊（PG ILIKE / sqlite LIKE）
"""
from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession


async def list_supers(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    exclude_super_id: uuid.UUID | None = None,
    limit: int = 20,
) -> list[dict]:
    """查所有可用 super agent；可选关键词模糊 + 排除自己。

    返回字段：super_id / name / description / fit_hint (description 第一行)。
    """
    from app.models.agent import Agent

    stmt = select(Agent).where(
        Agent.kind == "super",
        Agent.is_enabled.is_(True),
    )
    if exclude_super_id is not None:
        stmt = stmt.where(Agent.id != exclude_super_id)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(or_(
            Agent.name.like(pattern),
            Agent.description.like(pattern),
            Agent.soul_md.like(pattern),
        ))
    stmt = stmt.order_by(Agent.name).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for a in rows:
        descr = a.description or ""
        first_line = descr.split("\n", 1)[0].strip() if descr else (
            (a.soul_md or "").split("\n", 1)[0].strip()
        )
        out.append({
            "super_id": str(a.id),
            "name": a.name,
            "description": descr,
            "fit_hint": first_line[:140],
        })
    return out
