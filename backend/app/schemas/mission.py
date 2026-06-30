"""Mission Pydantic schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MissionStatus = Literal["draft", "active", "archived"]
# M1：运行态状态机
MissionRuntimeStatus = Literal[
    "stopped",
    "starting",
    "running",
    "stopping",
    "error",
]
MissionLifecycleAction = Literal["start", "stop", "restart", "clear_memory", "run_once"]


class MissionBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    supervisor_agent_id: uuid.UUID
    auto_approve: bool = True  # 默认全自动·完全授权（与 Mission 模型默认一致）
    context_compression_threshold: int = Field(
        default=300_000,
        ge=1_000,
        le=1_000_000,
        description=(
            "上下文自动压缩阈值。"
            "**单位：~tokens（用 len(text) 做保守估计）**。"
            "估算对象是**整个组装 context**：supervisor 系统提示 + memory_md + "
            "workspace 快照（worker state + artifact meta）+ 未压缩对话。"
            "超过阈值时 compression_service.maybe_compress_context 会用 LLM 摘要把较早的"
            "消息压缩写入 BranchAgentMemory.memory_md，仅保留最近 keep_recent 条原文。"
            "默认 300_000 ≈ 30 万 token（覆盖 1M 窗口的 1/3 安全边界）。"
        ),
    )


class MissionCreate(MissionBase):
    pass


class MissionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    supervisor_agent_id: uuid.UUID | None = None
    auto_approve: bool | None = None
    context_compression_threshold: int | None = Field(default=None, ge=1_000, le=1_000_000)


class MissionPublic(MissionBase):
    model_config = ConfigDict(from_attributes=True)

    # 读模型不再对已持久化的 slug 做字符集校验：slug 的合法性在**写入路径**
    # （MissionCreate / slug 生成器）保证；读回时再校验只会让一行历史脏 slug
    # 炸掉整个 /api/missions/all（→ 后台所有 super 显示「暂无运营实例」、进不去 mission）。
    slug: str = Field(min_length=1, max_length=128)

    id: uuid.UUID
    status: MissionStatus
    runtime_status: MissionRuntimeStatus = "stopped"
    lifecycle_status: str | None = None  # FSM 权威态；前端 mission badge 用（ADR-008 Lifecycle）
    is_system: bool = False  # ADR-015 · 平台系统 Mission（Builder）不可删除
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class MissionRuntimePublic(BaseModel):
    """M1：GET /api/missions/{id}/runtime 返回内容。"""

    model_config = ConfigDict(from_attributes=True)

    mission_id: uuid.UUID
    status: MissionRuntimeStatus
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_error: str | None = None
    current_step: str | None = None
    run_count: int = 0


class MissionDetail(MissionPublic):
    """ADR-027 · 节点版退役后 MissionDetail 不再含 nodes；保留作为 detail 视图占位
    （未来可挂 super 声明的 required_capabilities / 实时 invocation 概览）。"""


class MissionActivationResponse(BaseModel):
    ok: bool
    status: MissionStatus
    issues: list[str] = Field(default_factory=list)


class MissionBulkModelUpdate(BaseModel):
    """批量修改 super 的主模型（ADR-027 · worker 不再按 mission 预绑，仅改 supervisor）。

    - `supervisor_model_id`：覆盖 `mission.supervisor_agent_id` 指向的 Agent 的 model_id
    字段可选；为 null 则不变。
    """

    supervisor_model_id: uuid.UUID | None = None


class MissionBulkModelUpdateResponse(BaseModel):
    updated_supervisor_agent_id: uuid.UUID | None = None
