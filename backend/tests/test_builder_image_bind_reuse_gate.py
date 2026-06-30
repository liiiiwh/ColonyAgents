"""A 修复的端到端洞：复用已有 worker 当出图节点时，也必须确保它绑定了图像模型。

原 bug（真实 e2e 测出）：design_agents 的「缺图像模型→不建+暂停 / 出图 worker 必绑 text2img」硬门槛
只覆盖「新建 worker」路径；当 Builder Supervisor 选择**复用**现成 worker（mission_add_node 直接挂一个
已存在的 agent，如 cover_designer）时，整条图像绑定逻辑被绕过 —— 挂进来的出图 worker `aux=[]`，
根本出不了图，却在方案里许诺了 text2img→真实模型。

这条测试钉死：Builder Supervisor 的 protocol_md 必须在 BUILD 阶段对「复用出图 worker」也加同样的
绑定硬门槛（补绑 or 不接入+暂停），而不是只在 design_agents 新建路径上。
"""
from __future__ import annotations

import pytest
from sqlalchemy import text as _sql_text

from app.db.init_db import seed_admin_user, seed_builder_project


@pytest.mark.asyncio
async def test_builder_protocol_guards_image_binding_on_worker_reuse(db_session):
    await seed_admin_user(db_session)
    await seed_builder_project(db_session)

    row = (
        await db_session.execute(
            _sql_text(
                "select protocol_md from agents where name = 'Builder Supervisor'"
            )
        )
    ).first()
    assert row is not None, "Builder Supervisor 应已被 seed"
    proto: str = row[0]

    # 复用路径必须出现：不把没绑图像模型的 worker 当出图节点接进来（独有 sentinel）
    assert "没绑图像模型" in proto, "BUILD 阶段缺『复用出图 worker 也要绑图像模型』硬门槛"
    # 补绑动作 + 固定 alias 必须在该硬门槛附近被点名
    assert "agent_aux_model_bind" in proto
    assert "text2img" in proto
