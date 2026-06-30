"""Agent Pydantic schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 辅助模型角色：chat-model / vision / image-generation / video-generation / embedding / rerank / custom
AuxModelRole = Literal[
    "chat",
    "vision",
    "image",
    "video",
    "embedding",
    "rerank",
    "tts",
    "stt",
    "custom",
]

# Agent / Skill 功能分类，管理后台按此分组渲染。
# - builder: Orchestrator chat 里的"建造者"（meta 层）
# - installer: 安装 ClawHub skill 的执行 Agent（可并行）
# - tester: sandbox 跑 mission_run_test 的 Agent
# - worker.*: 真正执行业务工作流的 Worker（分领域）
# - utility: 通用辅助 Agent（解析、翻译、判断等）
# - custom: 用户自定义未归类
AgentCategory = Literal[
    "builder",
    "installer",
    "tester",
    "worker.web",
    "worker.data",
    "worker.io",
    "worker.creative",
    "worker.imported",  # ADR-019 · 从外部 prompt 库导入的 advisory worker
    "utility",
    "custom",
]


class AgentBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    category: AgentCategory = "custom"
    # None = use the platform default model (resolved at runtime by kind). ADR-017.
    model_id: uuid.UUID | None = None
    soul_md: str = ""
    protocol_md: str = ""
    domain_memory_md: str = ""
    # le=80 对齐 SupervisorSpec：Builder 等编排型 super 需更高迭代（reclimit=max_iter*2）。
    max_iterations: int = Field(default=10, ge=1, le=80)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_output_tokens: int = Field(
        default=30000,
        ge=256,
        le=64000,
        description=(
            "单次 LLM 调用的最大输出 token（LiteLLM max_tokens）。默认 30000：给交付物 JSON "
            "/ Markdown + LLM 序言 + tool_call 元信息足够余量，彻底规避 length-stop 截断。"
            "命中 length 上限时由 ResilientChatLiteLLM 自动续写（仅纯文本；tool_call 参数被截"
            "会抛错，让 Agent 分块写）。"
        ),
    )
    extra_config: dict = Field(default_factory=dict)
    is_enabled: bool = True
    is_system: bool = Field(
        default=False,
        description="ADR-015 · 平台系统对象（Builder Supervisor / builtin worker）不可删除；前端隐删除钮。",
    )
    produces_deliverable: bool = Field(
        default=False,
        description=(
            "True = 该 Agent 的 workspace_write 被视为交付物：自动上传 S3，"
            "同节点覆盖写（artifacts 数组里同 node 只保留最新一条），前端 Workspace "
            "面板与交付物进度条呈现；False = 过程态，仅保存 branch state。"
        ),
    )
    enable_thinking: bool = Field(
        default=False,
        description="【旧字段，保留兼容】请改用 thinking_level；仅在 thinking_level 缺省时作回退。",
    )
    thinking_level: Literal["off", "low", "medium", "high"] = Field(
        default="off",
        description=(
            "模型内置思考档位。按主模型家族自动映射成各家具体参数：\n"
            "- off    → claude thinking.disabled / gemini thinkingBudget=0(pro 128) / 其它 reasoning_effort=low\n"
            "- low    → gemini thinkingBudget=512  / claude budget_tokens=2000  / reasoning_effort=low\n"
            "- medium → gemini thinkingBudget=2048 / claude budget_tokens=8000  / reasoning_effort=medium\n"
            "- high   → gemini thinkingBudget=8192 / claude budget_tokens=16000 / reasoning_effort=high\n"
            "默认 off（最省 token / 最快首 token）；仍可用 extra_config 精调。"
        ),
    )
    # v3 R24：agent 角色 — worker / super / builder / installer / tester / utility
    kind: str | None = Field(
        default=None,
        description=(
            "v3 角色：worker（被动执行）/ super（主动调度）/ builder / installer / tester / utility。"
            "agent_create 时 None → 由 category 推断（worker.* → 'worker'；builder → 'builder'；"
            "其它 → 'utility'）。super 必须显式传 'super' 触发 R24 强落地默认（max_iterations=40）。"
        ),
    )
    capability: str | None = Field(
        default=None,
        description="worker 能力 slug（如 xhs_ops / data_analytics），供 super invoke_worker 按 capability 选；其它 kind 留空。",
    )


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    category: AgentCategory | None = None
    model_id: uuid.UUID | None = None
    soul_md: str | None = None
    protocol_md: str | None = None
    domain_memory_md: str | None = None
    max_iterations: int | None = Field(default=None, ge=1, le=80)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=256, le=64000)
    extra_config: dict | None = None
    is_enabled: bool | None = None
    produces_deliverable: bool | None = None
    enable_thinking: bool | None = None
    thinking_level: Literal["off", "low", "medium", "high"] | None = None
    kind: str | None = None
    capability: str | None = None


class AgentSkillBinding(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    skill_id: uuid.UUID
    config: dict = Field(default_factory=dict)


class AgentMCPBinding(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mcp_server_id: uuid.UUID
    tool_filter: list[str] | None = None


class AgentAuxModelBinding(BaseModel):
    """Agent 的辅助模型绑定。"""

    model_config = ConfigDict(from_attributes=True)

    model_id: uuid.UUID | None = None
    role: AuxModelRole = "custom"
    alias: str | None = Field(
        default=None, max_length=64, description="Agent 内唯一短名，供工具引用"
    )
    config: dict = Field(default_factory=dict)


class AgentAuxModelBindingInput(BaseModel):
    role: AuxModelRole = "custom"
    alias: str | None = Field(default=None, max_length=64)
    config: dict = Field(default_factory=dict)


class ModelInfo(BaseModel):
    """为前端展示：Detail 中把主模型的关键信息塞进来（provider / model_id / context / vision）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    model_id: str
    display_name: str
    model_type: str
    context_window: int = 0
    supports_vision: bool = False
    supports_function_calling: bool = False


class AgentPublic(AgentBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # super 身份（URL slug + 显示名）；worker/系统对象可能为 None
    slug: str | None = None
    display_name: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentDetail(AgentPublic):
    skill_bindings: list[AgentSkillBinding] = Field(default_factory=list)
    mcp_bindings: list[AgentMCPBinding] = Field(default_factory=list)
    aux_model_bindings: list[AgentAuxModelBinding] = Field(default_factory=list)
    # 主模型扩展信息（UI 展示用）
    model: ModelInfo | None = None


class AgentTestRequest(BaseModel):
    input: str = Field(min_length=1, description="单轮对话输入")


class AgentTestResponse(BaseModel):
    ok: bool
    output: str | None = None
    tools_loaded: int = 0
    error: str | None = None
