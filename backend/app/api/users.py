"""用户管理 API。只有 admin 可访问全部 CRUD。

对应前端 /admin/users 页面。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.deps import AdminUser, DBSession
from app.schemas.auth import UserCreate, UserPublic, UserUpdate
from app.services import user_service

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserPublic])
async def list_users(
    _: AdminUser,
    db: DBSession,
    search: str | None = None
) -> list[UserPublic]:
    users = await user_service.list_users(db, search=search)
    return [UserPublic.model_validate(u) for u in users]


@router.get("/search", response_model=list[UserPublic])
async def search_users(
    _: AdminUser,
    db: DBSession,
    q: str,
    limit: int = 10
) -> list[UserPublic]:
    """搜索用户（按用户名或邮箱）"""
    users = await user_service.search_users(db, query=q, limit=limit)
    return [UserPublic.model_validate(u) for u in users]


@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate, admin: AdminUser, db: DBSession
) -> UserPublic:
    try:
        user = await user_service.create_user(db, payload, actor=admin)
    except ValueError as exc:
        # 超级管理员规则 / 角色非法 → 400；用户名 / 邮箱冲突 → 409
        msg = str(exc)
        if "已被占用" in msg:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=msg) from exc
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=msg) from exc
    return UserPublic.model_validate(user)


@router.get("/{user_id}", response_model=UserPublic)
async def get_user(
    user_id: uuid.UUID, _: AdminUser, db: DBSession
) -> UserPublic:
    user = await user_service.get_user(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return UserPublic.model_validate(user)


@router.put("/{user_id}", response_model=UserPublic)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    admin: AdminUser,
    db: DBSession,
) -> UserPublic:
    user = await user_service.get_user(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="用户不存在")
    try:
        updated = await user_service.update_user(db, user, payload, actor=admin)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UserPublic.model_validate(updated)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID, admin: AdminUser, db: DBSession
) -> None:
    user = await user_service.get_user(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="用户不存在")
    try:
        await user_service.delete_user(db, user, actor=admin)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
