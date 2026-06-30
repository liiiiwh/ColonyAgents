"""v6.A · Missions API。

Mission = SuperAgent 的一次实例化。CRUD：
- POST /api/missions             -- spawn (用户点 + 新建 Mission)
- GET  /api/missions             -- 列当前用户的 missions（可按 super_agent_id 过滤）
- GET  /api/missions/{slug}      -- 详情（goal_spec / lifecycle / sessions 列表）
- DELETE /api/missions/{slug}    -- soft delete

Mission 在 DB 里仍是 `projects` 表（语义升级；不迁移 schema）。
URL & API & UI 一律说 Mission；CONTEXT.md > "Mission" 定义。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import CurrentUser, DBSession
from app.models.agent import Agent
from app.models.mission import Mission

router = APIRouter(prefix="/api/missions", tags=["missions"])


# ─────────────────────────── Schemas ───────────────────────────


class MissionPublic(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    super_agent_id: uuid.UUID
    super_slug: str | None = None
    super_name: str | None = None
    lifecycle_status: str
    goal_hint: str | None = None
    goal_spec: dict | None = None  # 已废弃（cand②：目标归 MissionMemory）；恒为 None，保字段防前端破
    is_system: bool = False  # 系统 mission（Builder / Worker-Opt）；前端据此从用户列表过滤
    created_at: str | None = None


class MissionCreateBody(BaseModel):
    super_agent_id: uuid.UUID
    name: str
    goal_hint: str | None = None


class MissionCreateResp(BaseModel):
    ok: bool
    mission: MissionPublic | None = None
    error: str | None = None


# ─────────────────────────── Endpoints ───────────────────────────


def _serialize_mission(p: Mission, super_agent: Agent | None = None) -> MissionPublic:
    wc = p.workflow_config or {}
    return MissionPublic(
        id=p.id,
        slug=p.slug,
        name=p.name,
        description=p.description,
        super_agent_id=p.supervisor_agent_id,
        # super 身份：优先 agent.slug/display_name（干净 URL+标题），回退 agent.name（老数据）
        super_slug=(getattr(super_agent, "slug", None) or getattr(super_agent, "name", None)) if super_agent else None,
        super_name=(getattr(super_agent, "display_name", None) or getattr(super_agent, "name", None)) if super_agent else None,
        lifecycle_status=getattr(p, "lifecycle_status", "stopped"),
        goal_hint=wc.get("goal_hint"),
        goal_spec=None,  # cand②：goal_spec 已废弃，不再回读（目标在 MissionMemory）
        is_system=getattr(p, "is_system", False),
        created_at=p.created_at.isoformat() if p.created_at else None,
    )


@router.post("", response_model=MissionCreateResp)
async def create_mission(
    body: MissionCreateBody,
    db: DBSession,
    user: CurrentUser,
) -> MissionCreateResp:
    """Q6 流程：用户点「+ 新建 Mission」→ 调本 endpoint → 跳 /mission/<slug>。

    super 第一次 tick 会看到 goal_hint，自然走 request_structured_input 收集 goal_spec。
    """
    from app.domain.builder.factory import spawn_mission

    try:
        ref = await spawn_mission(
            db,
            super_agent_id=body.super_agent_id,
            name=body.name,
            created_by=user.id,
            goal_hint=body.goal_hint,
        )
    except ValueError as exc:
        return MissionCreateResp(ok=False, error=str(exc))

    proj = await db.get(Mission, ref.mission_id)
    super_agent = await db.get(Agent, body.super_agent_id)

    # 「它要做什么」(goal_hint) 处理（best-effort：mission 已创建，下面任一失败都不影响返回成功）
    #   - 填了 → 当作用户在聊天框里输入的第一句话：写主 thread(role=user) + 自动 start daemon
    #     + 立即触发 super 处理（post_user_message_and_trigger）。
    #   - 没填 → 主动发一条固定问候语（assistant 角色，admin 在系统设置可改）邀请用户说需求；
    #     不触发 super，等用户回复。
    import logging as _logging
    _log = _logging.getLogger(__name__)
    try:
        goal = (body.goal_hint or "").strip()
        if goal:
            from app.api.super_conversation import post_user_message_and_trigger
            await post_user_message_and_trigger(
                db, proj, goal,
                user_id=user.id, sup=super_agent,
                # source='user_chat'：goal_hint 是用户亲手填的「它要做什么」，等同于在
                # 聊天框敲下的第一句话 → 必须以真人身份落库（前端 systemUserKind 据此渲染成
                # 蓝色用户气泡，而非 🤖 系统·自动）。
                meta={"source": "user_chat"},
            )
        else:
            from app.core import system_settings as _ss
            from app.services import messaging_service as _msg_svc
            greeting = await _ss.get(
                db,
                _ss.MISSION_EMPTY_GOAL_PROMPT_KEY,
                _ss.MISSION_EMPTY_GOAL_PROMPT_DEFAULT,
            )
            await _msg_svc.append_message(
                db, proj.id, "main",
                role="assistant",
                content=greeting,
                meta={"type": "mission_greeting"},
            )
    except Exception:
        _log.exception("[create_mission] goal_hint 处理失败（不阻塞，mission 已创建）")

    return MissionCreateResp(
        ok=True,
        mission=_serialize_mission(proj, super_agent),
    )


@router.get("", response_model=list[MissionPublic])
async def list_missions(
    db: DBSession,
    user: CurrentUser,
    super_agent_id: uuid.UUID | None = Query(None, description="若给 → 只列该 super 的 missions"),
) -> list[MissionPublic]:
    """列 missions。admin 看所有；普通用户看自己创建的（暂未实现 — 当前 admin 共享）。"""
    stmt = select(Mission).order_by(Mission.created_at.desc())
    if super_agent_id is not None:
        stmt = stmt.where(Mission.supervisor_agent_id == super_agent_id)
    projects = (await db.execute(stmt)).scalars().all()

    # 批量取 super agents
    super_ids = {p.supervisor_agent_id for p in projects if p.supervisor_agent_id}
    supers = (await db.execute(
        select(Agent).where(Agent.id.in_(super_ids))
    )).scalars().all() if super_ids else []
    by_id = {a.id: a for a in supers}

    return [_serialize_mission(p, by_id.get(p.supervisor_agent_id)) for p in projects]


@router.get("/{slug}", response_model=MissionPublic)
async def get_mission(
    slug: str,
    db: DBSession,
    _user: CurrentUser,
) -> MissionPublic:
    """通过 slug 拿 mission 详情（前端 /mission/<slug> 工作台首屏调）。"""
    proj = (await db.execute(
        select(Mission).where(Mission.slug == slug)
    )).scalar_one_or_none()
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"mission slug={slug!r} 不存在")
    super_agent = await db.get(Agent, proj.supervisor_agent_id)
    return _serialize_mission(proj, super_agent)
