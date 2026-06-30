"""Skill / MCP Server Pydantic schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SkillType = Literal["instruction", "tool_builtin"]
MCPServerType = Literal["stdio", "http"]

# 与 AgentCategory 同枚举（避免循环 import，这里独立维护一份字面量）
SkillCategory = Literal[
    "builder",
    "installer",
    "tester",
    "worker.web",
    "worker.data",
    "worker.io",
    "worker.creative",
    "utility",
    "custom",
]


# ── Skill ──
class SkillBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str = Field(default="", max_length=512)
    description_en: str | None = Field(default=None, max_length=512)
    version: str = Field(default="0.1.0", max_length=32)
    category: SkillCategory = "custom"
    skill_type: SkillType
    content_md: str = ""
    builtin_ref: str | None = None
    config_schema: dict = Field(default_factory=dict)
    is_enabled: bool = True


class SkillCreate(SkillBase):
    pass


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    description_en: str | None = Field(default=None, max_length=512)
    version: str | None = Field(default=None, max_length=32)
    category: SkillCategory | None = None
    content_md: str | None = None
    config_schema: dict | None = None
    is_enabled: bool | None = None


class SkillPublic(SkillBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    is_builtin: bool
    created_at: datetime
    updated_at: datetime


# ── MCP Server ──
class MCPServerBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    server_type: MCPServerType
    command: list[str] | None = None
    env_vars: dict | None = None
    url: str | None = None
    headers: dict | None = None
    is_enabled: bool = True
    # 本地 MCP server 启动命令（http 模式可用；为空则不支持自动重启）
    startup_command: list[str] | None = None
    startup_cwd: str | None = None


class MCPServerCreate(MCPServerBase):
    pass


class MCPServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    command: list[str] | None = None
    env_vars: dict | None = None
    url: str | None = None
    headers: dict | None = None
    is_enabled: bool | None = None
    startup_command: list[str] | None = None
    startup_cwd: str | None = None


class MCPServerPublic(MCPServerBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class MCPToolInfo(BaseModel):
    name: str
    description: str
    input_schema: dict = Field(default_factory=dict)


class MCPTestResponse(BaseModel):
    reachable: bool
    error: str | None = None
    tools: list[MCPToolInfo] = Field(default_factory=list)
