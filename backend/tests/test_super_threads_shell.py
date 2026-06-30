"""无 standing mission 的 super（如 Builder）入工作台：superThreads 返回空壳而非 404。

让「进入工作台」对零 mission 的 super 也能直接进工作台（空 mission 列表 + 自动弹新建），
省掉中间的 /super 角色页。
"""
from __future__ import annotations

import pytest

from app.api.observe import super_threads
from app.db.init_db import seed_admin_user, seed_builder_project
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_super_threads_returns_shell_for_no_mission_super(db_session):
    await seed_admin_user(db_session)
    await seed_builder_project(db_session)  # Builder super slug='builder'，无 standing mission

    resp = await super_threads("builder", db_session, None)  # _u 仅路由层鉴权，函数体不用

    assert resp["mission_id"] is None, "无 mission → 空壳 mission_id 应为 None"
    assert resp["supervisor_agent_id"], "空壳必须带 supervisor_agent_id（工作台据此拉空 mission 列表）"
    assert resp["threads"] == []
    assert resp["super_slug"] == "builder"


@pytest.mark.asyncio
async def test_super_threads_404_for_unknown_slug(db_session):
    await seed_admin_user(db_session)
    await seed_builder_project(db_session)
    with pytest.raises(HTTPException) as ei:
        await super_threads("no-such-super-or-mission", db_session, None)
    assert ei.value.status_code == 404
