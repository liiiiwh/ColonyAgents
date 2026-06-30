"""Auth 相关 Pydantic v2 请求 / 响应 schema。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    """OAuth2 Password Flow 之外也支持 JSON 登录。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserPublic(BaseModel):
    """用户公开信息（不含密码）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime


# 用户角色：
# - admin：全部权限（后台 + 会话）
# - user：仅会话使用权限（/projects 列表 + /p/[slug]；禁止进 /admin/*）
UserRole = Literal["admin", "user"]


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    role: UserRole = "user"
    is_active: bool = True


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    # 不传或为空字符串 → 不改密码；非空则更新
    password: str | None = Field(default=None, min_length=6, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None
