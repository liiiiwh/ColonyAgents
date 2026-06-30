"""M2：Mission Schedule CRUD + 事件触发 + 手动触发。

挂在 `/api/missions/{mission_id}` 下，与 lifecycle 同级。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import AdminUser, DBSession
from app.models.mission import MissionSchedule
from app.schemas.schedule import (
    EventFireRequest,
    ScheduleCreate,
    SchedulePublic,
    ScheduleUpdate,
    _validate_expr,
)
from app.services import mission_service, scheduler_service

router = APIRouter(prefix="/api/missions", tags=["schedules"])


def _to_public(s: MissionSchedule) -> SchedulePublic:
    # 若内存 scheduler 知道 next_fire_at（cron / interval），覆盖 DB 的过时值
    if s.kind in ("cron", "interval"):
        nfa = scheduler_service.get_next_fire_at(s.id)
        if nfa is not None:
            s.next_fire_at = nfa
    return SchedulePublic.model_validate(s)


@router.get(
    "/{mission_id}/schedules",
    response_model=list[SchedulePublic],
)
async def list_schedules(
    mission_id: uuid.UUID, _: AdminUser, db: DBSession
) -> list[SchedulePublic]:
    project = await mission_service.get_mission(db, mission_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mission 不存在")
    rows = await db.execute(
        select(MissionSchedule)
        .where(MissionSchedule.mission_id == mission_id)
        .order_by(MissionSchedule.created_at.asc())
    )
    return [_to_public(s) for s in rows.scalars().all()]


@router.post(
    "/{mission_id}/schedules",
    response_model=SchedulePublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    mission_id: uuid.UUID,
    payload: ScheduleCreate,
    admin: AdminUser,
    db: DBSession,
) -> SchedulePublic:
    project = await mission_service.get_mission(db, mission_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mission 不存在")
    try:
        _validate_expr(payload.kind, payload.expr)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    sched = MissionSchedule(
        mission_id=mission_id,
        name=payload.name,
        kind=payload.kind,
        expr=payload.expr.strip(),
        payload_template=payload.payload_template,
        enabled=payload.enabled,
        created_by=admin.id,
    )
    db.add(sched)
    await db.commit()
    await db.refresh(sched)
    scheduler_service.reschedule_one(sched)
    return _to_public(sched)


@router.put(
    "/{mission_id}/schedules/{schedule_id}",
    response_model=SchedulePublic,
)
async def update_schedule(
    mission_id: uuid.UUID,
    schedule_id: uuid.UUID,
    payload: ScheduleUpdate,
    _: AdminUser,
    db: DBSession,
) -> SchedulePublic:
    sched = await db.get(MissionSchedule, schedule_id)
    if sched is None or sched.mission_id != mission_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Schedule 不存在")
    data = payload.model_dump(exclude_unset=True)
    # 校验 expr 合法性（与 ScheduleCreate 同规则）
    if "kind" in data or "expr" in data:
        new_kind = data.get("kind", sched.kind)
        new_expr = (data.get("expr") or sched.expr).strip()
        try:
            _validate_expr(new_kind, new_expr)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    for k, v in data.items():
        setattr(sched, k, v.strip() if k == "expr" and isinstance(v, str) else v)
    await db.commit()
    await db.refresh(sched)
    scheduler_service.reschedule_one(sched)
    return _to_public(sched)


@router.delete(
    "/{mission_id}/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_schedule(
    mission_id: uuid.UUID,
    schedule_id: uuid.UUID,
    _: AdminUser,
    db: DBSession,
) -> None:
    sched = await db.get(MissionSchedule, schedule_id)
    if sched is None or sched.mission_id != mission_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Schedule 不存在")
    scheduler_service.delete_one(schedule_id)
    await db.delete(sched)
    await db.commit()


@router.post(
    "/{mission_id}/schedules/{schedule_id}/fire",
    response_model=SchedulePublic,
)
async def manual_fire(
    mission_id: uuid.UUID,
    schedule_id: uuid.UUID,
    _: AdminUser,
    db: DBSession,
) -> SchedulePublic:
    """手动触发一次（不影响下次自动 fire）。"""
    sched = await db.get(MissionSchedule, schedule_id)
    if sched is None or sched.mission_id != mission_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Schedule 不存在")
    # fire_one 内部 open 自己的 session，先 commit 当前以释放锁
    await db.commit()
    await scheduler_service.fire_one(schedule_id)
    # 重新拿一份最新的
    await db.refresh(sched)
    return _to_public(sched)


@router.post(
    "/{mission_id}/events/{event_name}",
    response_model=list[SchedulePublic],
)
async def fire_event(
    mission_id: uuid.UUID,
    event_name: str,
    payload: EventFireRequest,
    _: AdminUser,
    db: DBSession,
) -> list[SchedulePublic]:
    """webhook：触发所有 kind='event' 且 expr=event_name 且 enabled 的 schedule。"""
    rows = await db.execute(
        select(MissionSchedule).where(
            MissionSchedule.mission_id == mission_id,
            MissionSchedule.kind == "event",
            MissionSchedule.expr == event_name,
            MissionSchedule.enabled.is_(True),
        )
    )
    matched = list(rows.scalars().all())
    if not matched:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"无 enabled 的 event 监听 '{event_name}'",
        )
    # commit 释放锁后再 fire
    await db.commit()
    for s in matched:
        await scheduler_service.fire_one(s.id, override_payload=payload.payload)
    # 重读
    out: list[SchedulePublic] = []
    for s in matched:
        await db.refresh(s)
        out.append(_to_public(s))
    return out
