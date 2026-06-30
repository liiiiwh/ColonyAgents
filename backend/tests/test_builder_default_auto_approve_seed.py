"""ADR-026 D1 · Builder Supervisor 种子默认关闭 mission 全自动。

全局默认是「新建 mission 全自动·完全授权」(True)，唯独 Builder super 在种子数据里把
extra_config.mission_default_auto_approve 设为 False —— 让 Builder 的设计会话回到
propose-confirm 人审（ADR-012），不会自动确认自己的设计方案直接开建。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.init_db import seed_admin_user, seed_builder_project
from app.models.agent import Agent


@pytest.mark.asyncio
async def test_builder_supervisor_seeded_with_auto_approve_default_false(db_session):
    await seed_admin_user(db_session)
    await seed_builder_project(db_session)

    sup = (await db_session.execute(
        select(Agent).where(Agent.slug == "builder")
    )).scalar_one()

    assert (sup.extra_config or {}).get("mission_default_auto_approve") is False, (
        "Builder Supervisor 种子必须把 mission_default_auto_approve 设为 False"
    )
