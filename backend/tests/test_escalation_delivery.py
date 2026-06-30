"""自迭代闭环：创建出来的 super 缺能力 → escalation → 回投到产出它的 builder 设计会话主线程
（按 built_by_mission_id），builder 据此进 DESIGN_WORKER 迭代。验证 super→builder 回路通。
"""
from datetime import datetime, UTC

import pytest
from sqlalchemy import select

from app.models.agent import Agent
from app.models.mission import Mission, MissionEscalation
from app.models.message import Message
from app.models.user import User
from app.services.escalation_dispatcher import deliver_escalation


@pytest.mark.asyncio
async def test_escalation_routed_to_origin_builder_mission(db_session, _patched_session_local):
    user = User(username="u", email="u@x.com", hashed_password="x", role="admin")
    builder_agent = Agent(name="Builder Supervisor", category="builder", kind="super", slug="builder")
    db_session.add_all([user, builder_agent])
    await db_session.flush()
    # +新建 builder 设计会话（产出 super 的 origin）
    design = Mission(name="物流调度排程", slug="mission-design", supervisor_agent_id=builder_agent.id,
                     created_by=user.id, workflow_config={})
    db_session.add(design)
    await db_session.flush()
    # 设计会话产出的 super（provenance: built_by_mission_id=design）+ 它的运行 mission
    super_agent = Agent(name="logi-super", kind="super", category="custom", slug="logi",
                        built_by_mission_id=design.id)
    db_session.add(super_agent)
    await db_session.flush()
    super_mission = Mission(name="物流运行", slug="logi-run", supervisor_agent_id=super_agent.id,
                            created_by=user.id, workflow_config={})
    db_session.add(super_mission)
    await db_session.flush()
    # super 升级：缺一个能力，请求 builder 加 worker
    esc = MissionEscalation(
        mission_id=super_mission.id, created_at=datetime.now(UTC), category="structural",
        severity="warn", summary="缺『跨区域调拨审批』能力", proposed_change="新建 dispatch_approver worker",
        fingerprint="fp-test-1", status="pending",
    )
    db_session.add(esc)
    await db_session.commit()

    await deliver_escalation(esc.id)

    # 设计会话主线程收到 [project-escalation from logi-run]，builder 据此可迭代
    msgs = (await db_session.execute(
        select(Message).where(Message.mission_id == design.id, Message.thread_key == "main")
    )).scalars().all()
    esc_msgs = [m for m in msgs if "[project-escalation from logi-run]" in (m.content or "")]
    assert len(esc_msgs) == 1, "super 升级未回投到 origin builder 设计会话"
    assert esc_msgs[0].meta.get("type") == "project_escalation"
    assert esc_msgs[0].meta.get("opened_by") == f"super:{super_agent.id}"  # 进 DESIGN_WORKER 路由

    await db_session.refresh(esc)
    assert esc.status == "delivered"
