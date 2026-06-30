"""用户 CRUD 服务层。

设计：
- 只有 admin 可以通过 /api/users CRUD 他人
- admin 不能把自己降级为非 admin（避免误操作导致无人能管后台）
- admin 不能删除自己
- 密码用 bcrypt 哈希；password 空 / None 表示保留原密码
- **超级管理员规则**（username='admin'）：
  - 仅超级管理员可 *创建* 新的 admin 角色账号（其他 admin 只能建 user）
  - 仅超级管理员可 *删除* 其他 admin 账号
  - 其他 admin 仍可以 CRUD 普通 user，并可自编辑（不含降级 / 停用自己）
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User
from app.schemas.auth import UserCreate, UserUpdate


#: 超级管理员用户名。
#: 只有该账号可以：
#: - 创建 admin 角色的新账号
#: - 将非 admin 用户提升为 admin
#: - 删除其它 admin 账号
SUPER_ADMIN_USERNAME = "admin"


async def list_users(db: AsyncSession, search: str | None = None) -> Sequence[User]:
    stmt = select(User)
    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(
            or_(
                User.username.ilike(search_term),
                User.email.ilike(search_term)
            )
        )
    stmt = stmt.order_by(User.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


async def search_users(db: AsyncSession, query: str, limit: int = 10) -> Sequence[User]:
    """搜索用户（按用户名或邮箱模糊匹配）"""
    search_term = f"%{query}%"
    stmt = (
        select(User)
        .where(
            or_(
                User.username.ilike(search_term),
                User.email.ilike(search_term)
            )
        )
        .order_by(User.username)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession, payload: UserCreate, *, actor: User
) -> User:
    # 仅超级管理员（username='admin'）可创建 admin 角色账号
    if payload.role == "admin" and actor.username != SUPER_ADMIN_USERNAME:
        raise ValueError(
            "普通管理员不能创建 admin 账号；此操作仅限超级管理员（admin）"
        )
    if await get_user_by_username(db, payload.username):
        raise ValueError(f"用户名 {payload.username!r} 已被占用")
    if await get_user_by_email(db, payload.email):
        raise ValueError(f"邮箱 {payload.email!r} 已被占用")
    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        is_active=payload.is_active,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(
    db: AsyncSession, user: User, payload: UserUpdate, *, actor: User
) -> User:
    if payload.email and payload.email != user.email:
        dup = await get_user_by_email(db, payload.email)
        if dup and dup.id != user.id:
            raise ValueError(f"邮箱 {payload.email!r} 已被占用")
        user.email = payload.email
    # role / is_active：admin 不能把**自己**降级或停用
    if payload.role is not None:
        if user.id == actor.id and payload.role != "admin":
            raise ValueError("不能把自己的角色从 admin 降级；请让其他管理员操作")
        # 仅超级管理员可将非 admin 用户提升为 admin
        if (
            payload.role == "admin"
            and user.role != "admin"
            and actor.username != SUPER_ADMIN_USERNAME
        ):
            raise ValueError(
                "普通管理员不能将用户提升为 admin；此操作仅限超级管理员（admin）"
            )
        user.role = payload.role
    if payload.is_active is not None:
        if user.id == actor.id and payload.is_active is False:
            raise ValueError("不能停用自己的账号")
        user.is_active = payload.is_active
    if payload.password:
        user.hashed_password = hash_password(payload.password)
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user: User, *, actor: User) -> None:
    if user.id == actor.id:
        raise ValueError("不能删除自己")
    # 删除目标是 admin 时，仅超级管理员 (username='admin') 可操作
    if user.role == "admin" and actor.username != SUPER_ADMIN_USERNAME:
        raise ValueError(
            "普通管理员不能删除其他 admin 账号；此操作仅限超级管理员（admin）"
        )
    # 防止最后一个 admin 被删
    if user.role == "admin":
        admins = (
            await db.execute(select(User).where(User.role == "admin", User.is_active.is_(True)))
        ).scalars().all()
        if len([u for u in admins if u.id != user.id]) == 0:
            raise ValueError("系统至少保留 1 个可用 admin，不能删除最后一个")
    await db.delete(user)
    await db.commit()
