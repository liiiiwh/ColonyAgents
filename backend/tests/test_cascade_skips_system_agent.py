"""级联删 mission 时，is_system 的系统 agent 永不被带走。

真出过的坑：Builder super 改成「无 standing mission」后，删它的最后一个设计会话（cascade_agents=True）
把 is_system 的 Builder Supervisor 一起删了。系统对象必须对级联删免疫。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.services import mission_service


async def _admin(db) -> uuid.UUID:
    u = User(username="adm-cascade", email="adm-cascade@x.com", hashed_password="x", role="admin")
    db.add(u)
    await db.flush()
    return u.id


@pytest.mark.asyncio
async def test_cascade_delete_never_removes_is_system_supervisor(db_session):
    admin_id = await _admin(db_session)
    sup = Agent(name="Sys Super", kind="super", category="builder", is_system=True)
    db_session.add(sup)
    await db_session.flush()
    m = Mission(
        name="design-session", slug="design-session-x",
        supervisor_agent_id=sup.id, created_by=admin_id, status="active",
    )
    db_session.add(m)
    await db_session.commit()

    res = await mission_service.delete_mission_with_optional_cascade_agents(
        db_session, project=m, cascade_agents=True
    )

    # mission gone, but the is_system supervisor survives
    assert (await db_session.execute(
        select(Mission).where(Mission.slug == "design-session-x")
    )).scalar_one_or_none() is None
    survived = (await db_session.execute(
        select(Agent).where(Agent.id == sup.id)
    )).scalar_one_or_none()
    assert survived is not None, "is_system 系统 super 不该被级联删"
    assert sup.id not in {x for x in (res.get("deleted_agents") or [])}
