"""Session / Branch / Message Pydantic schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MessageRole = Literal["user", "assistant", "system", "agent_log"]
SessionStatus = Literal["active", "completed", "abandoned"]
SessionScope = Literal["orchestrator", "daemon", "observation_legacy"]
ArtifactType = Literal["markdown", "text", "json", "image", "html", "file", "3d-model", "video"]


class Artifact(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: ArtifactType
    label: str
    content: str | None = None
    s3_key: str | None = None
    s3_url: str | None = None
    media_type: str = "text/plain"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NodeWorkspace(BaseModel):
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    state: dict = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)


# ── Session ──
class SessionCreate(BaseModel):
    mission_id: uuid.UUID | None = None
    project_slug: str | None = None
    title: str | None = None

    def validate_target(self) -> None:
        if not self.mission_id and not self.project_slug:
            raise ValueError("mission_id 或 project_slug 至少需要提供一个")


class SessionProgress(BaseModel):
    """当前会话最新 branch 的工作流进度摘要（供前端会话列表渲染）。"""

    current_branch_id: uuid.UUID | None
    current_branch_label: str | None = None
    total_nodes: int
    completed_nodes: int
    current_node_name: str | None = None
    current_node_agent_name: str | None = None
    is_delivered: bool = False


class SessionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mission_id: uuid.UUID
    user_id: uuid.UUID | None
    title: str | None
    status: SessionStatus
    scope: SessionScope = "orchestrator"
    created_at: datetime
    updated_at: datetime
    progress: SessionProgress | None = None


class BranchPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    parent_branch_id: uuid.UUID | None
    branch_number: int
    version_label: str
    description: str
    is_current: bool
    thread_id: str
    workspace: dict
    last_active_at: datetime
    created_at: datetime
    task_group: str | None = None


class BranchList(BaseModel):
    branches: list[BranchPublic]


class MessagePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # ADR-018 step5/H · session_id/branch_id 退役中（新消息为 NULL）；(mission_id, thread_key) 是真键
    session_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    mission_id: uuid.UUID | None = None
    thread_key: str | None = None
    role: MessageRole
    content: str
    meta: dict = Field(default_factory=dict)
    token_count: int | None = None
    is_compressed: bool
    created_at: datetime


class Attachment(BaseModel):
    """多模态附件。

    - type=image：content 为图片 URL 或 data URI（data:image/png;base64,...）
    - type=file：content 为文件内容（建议 text/*）；binary 请先通过 /api/storage/upload 得到 key/url
    - type=text：content 直接作为额外文本片段
    """

    type: Literal["image", "file", "text"]
    name: str | None = None
    media_type: str | None = None
    content: str = Field(description="URL / data URI / 文本内容")


class ChatRequest(BaseModel):
    """与 AI SDK 的 useChat 对齐的最小负载。"""

    messages: list[dict] = Field(default_factory=list)
    # 兼容前端简单 API 调用
    message: str | None = None
    attachments: list[Attachment] = Field(
        default_factory=list, description="用户附件（图片 / 文件 / 额外文本）"
    )


class RollbackRequest(BaseModel):
    node_name: str = Field(min_length=1)
    reason: str = ""
