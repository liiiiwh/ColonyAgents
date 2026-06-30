"""Skill CRUD API。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.deps import AdminUser, DBSession
from app.schemas.skill import SkillCreate, SkillPublic, SkillUpdate
from app.services import skill_service

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("", response_model=list[SkillPublic])
async def list_skills(_: AdminUser, db: DBSession) -> list[SkillPublic]:
    skills = await skill_service.list_skills(db)
    return [SkillPublic.model_validate(s) for s in skills]


@router.post("", response_model=SkillPublic, status_code=status.HTTP_201_CREATED)
async def create_skill(payload: SkillCreate, _: AdminUser, db: DBSession) -> SkillPublic:
    if await skill_service.get_skill_by_slug(db, payload.slug):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="slug 已存在")
    if payload.skill_type == "tool_builtin" and not payload.builtin_ref:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="tool_builtin 必须提供 builtin_ref")
    skill = await skill_service.create_skill(db, payload)
    return SkillPublic.model_validate(skill)


@router.get("/{skill_id}", response_model=SkillPublic)
async def get_skill(skill_id: uuid.UUID, _: AdminUser, db: DBSession) -> SkillPublic:
    skill = await skill_service.get_skill(db, skill_id)
    if not skill:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="skill 不存在")
    return SkillPublic.model_validate(skill)


@router.put("/{skill_id}", response_model=SkillPublic)
async def update_skill(
    skill_id: uuid.UUID, payload: SkillUpdate, _: AdminUser, db: DBSession
) -> SkillPublic:
    skill = await skill_service.get_skill(db, skill_id)
    if not skill:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="skill 不存在")
    # 内置 Skill 只允许改 is_enabled（其他字段由 seed 控制）
    if skill.is_builtin:
        allowed = {"is_enabled"}
        leaked = set(payload.model_dump(exclude_unset=True).keys()) - allowed
        if leaked:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"内置 Skill 仅允许修改 {sorted(allowed)}，不得改 {sorted(leaked)}",
            )
    updated = await skill_service.update_skill(db, skill, payload)
    return SkillPublic.model_validate(updated)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: uuid.UUID, _: AdminUser, db: DBSession) -> None:
    skill = await skill_service.get_skill(db, skill_id)
    if not skill:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="skill 不存在")
    try:
        await skill_service.delete_skill(db, skill)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
