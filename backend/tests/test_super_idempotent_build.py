"""builder 幂等：一个 builder 设计会话（主 builder mission 或 +新建 mission）已建过一个
super 后，再次构建应复用、绝不重建第二个。根因：旧不变量只认 slug=='builder' 的主 mission，
+新建 设计会话（slug!='builder'）跳过 → 一次会话重复建出 xxx + xxx-v2。
"""
import uuid

import pytest

from app.domain.builder.factory import existing_super_for_builder_mission
from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User


async def _seed(db):
    user = User(username="u", email="u@x.com", hashed_password="x", role="admin")
    builder_sup = Agent(name="Builder Supervisor", kind="super", category="builder",
                        slug="builder", display_name="Colony Builder")
    db.add_all([user, builder_sup])
    await db.flush()
    return user, builder_sup


@pytest.mark.asyncio
async def test_reuse_for_plus_new_builder_mission(db_session):
    user, builder_sup = await _seed(db_session)
    # +新建 设计会话（slug != 'builder'，但 supervisor 是 builder super）
    design = Mission(name="招聘简历筛选", slug="mission-x", supervisor_agent_id=builder_sup.id,
                     created_by=user.id, workflow_config={})
    db_session.add(design)
    await db_session.flush()
    # 它已建出的 super
    built = Agent(name="resume-screening-supervisor", kind="super", category="custom",
                  slug="resume-screening", built_by_mission_id=design.id)
    db_session.add(built)
    await db_session.commit()

    found = await existing_super_for_builder_mission(db_session, design.id)
    assert found is not None and found.id == built.id  # +新建 会话也走幂等复用


@pytest.mark.asyncio
async def test_none_when_no_super_built_yet(db_session):
    user, builder_sup = await _seed(db_session)
    design = Mission(name="x", slug="mission-y", supervisor_agent_id=builder_sup.id,
                     created_by=user.id, workflow_config={})
    db_session.add(design)
    await db_session.commit()
    assert await existing_super_for_builder_mission(db_session, design.id) is None


@pytest.mark.asyncio
async def test_none_for_non_builder_mission(db_session):
    """普通（非 builder）super 的 mission 不触发幂等复用。"""
    user = User(username="u2", email="u2@x.com", hashed_password="x", role="admin")
    normal_sup = Agent(name="Normal Super", kind="super", category="custom", slug="normal")
    db_session.add_all([user, normal_sup])
    await db_session.flush()
    m = Mission(name="run", slug="run1", supervisor_agent_id=normal_sup.id, created_by=user.id)
    db_session.add(m)
    await db_session.commit()
    assert await existing_super_for_builder_mission(db_session, m.id) is None
