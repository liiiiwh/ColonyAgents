"""AgentSpec / SuperSpec / WorkerSpec · v6.

替代 Builder LLM 6+ tool 编排的"流水线散在 protocol_md prose"模式：
Builder 现在只生成一份 spec_json，factory.apply_*_spec(spec) 一次事务化落库。

设计：
- AgentSpec = 公共字段（name / slug / description / model_id / soul_md / protocol_md / max_iter / temp / enable_thinking）
- SuperSpec = 多 goal / capabilities / approval_channel / schedule / extra skills
- WorkerSpec = capability + capability_contract + skills + mcp
- 校验：name 非空，slug 合法（[a-z0-9_-]），model_id UUID

不变式：
- spec 不带状态（不能反映 DB 现状）；要查现状去 list_agents / list_workers
- factory 调用是幂等的 by name+slug：upsert 模式，重复 apply 同一 spec → update 不重建
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*$")


class AuxModelBinding(BaseModel):
    """绑给 Agent 的辅助模型（图像/视频/embedding 等）。

    运行时 `invoke_aux_model(alias_or_role='image')` 按 role/alias 找到它。一个图片 worker
    必须带一条 role='image' 的绑定，否则建得出架子却出不了图。
    """
    model_config = ConfigDict(extra="forbid")

    role: str = Field(default="custom", max_length=32,
                      description="chat / vision / image / video / embedding / rerank / tts / stt / custom")
    model_id: uuid.UUID = Field(...,
        description="辅助 LLMModel UUID（list_models(model_type='image'/'video'/'embedding') 拿）")
    alias: Optional[str] = Field(default=None, max_length=64,
                                 description="Agent 内唯一短名，供 invoke_aux_model(alias_or_role=...) 引用")


class AgentSpec(BaseModel):
    """所有 Agent (super/worker/builder) 共用基础字段。"""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    slug: str = Field(..., min_length=1, max_length=128,
                      description="URL-safe slug；用于 project.slug / agent 显示")
    model_id: uuid.UUID = Field(..., description="LLMModel UUID（list_models 拿）")
    description: str = ""
    soul_md: str = ""
    protocol_md: str = ""
    max_iterations: int = Field(default=10, ge=1, le=50)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    enable_thinking: bool = False
    extra_config: dict = Field(default_factory=dict)
    skills: list[str] = Field(default_factory=list,
                              description="额外要绑的 skill slug；空 = 仅默认自动绑")
    aux_models: list[AuxModelBinding] = Field(default_factory=list,
        description="辅助模型绑定（图像/视频/embedding）；图片 worker 必带一条 role='image'，"
                    "建 worker 时一并落库，无需再单独调 agent_aux_model_bind")

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(f"slug must match {_SLUG_RE.pattern}: got {v!r}")
        return v


class SuperSpec(AgentSpec):
    """SuperAgent spec —— Builder 设计一个 super 时生成的完整定义。

    factory.apply_super_spec(spec) 会一次性：
      1) create_agent(kind='super', enable_thinking=True 默认)
      2) auto-bind 必需 super skills (invoke_worker / request_approval / memory_* …)
      3) bind 用户额外指定 skills
      4) mission_create(slug, supervisor_agent_id)
      5) optional schedule_create
      6) optional mission_set_approval_channel
    """
    kind: Literal["super"] = "super"
    goal_spec: dict = Field(default_factory=dict,
                            description="{description, completion_criteria, must_have_capabilities}")
    capabilities: list[str] = Field(default_factory=list,
                                    description="该 super 依赖的 capability slugs")
    schedule: Optional[dict] = Field(default=None,
                                     description="{kind, expr, payload_template?}；省则不挂 schedule")
    approval_channel: Optional[dict] = Field(default=None,
                                             description="{clawbot_account_id, reviewer_wechat_ids}")
    auto_start: bool = True

    # super 默认强大脑
    enable_thinking: bool = True
    max_iterations: int = Field(default=40, ge=1, le=80)
    temperature: float = 0.5

    def to_extra_config(self) -> dict:
        out = dict(self.extra_config or {})
        if self.goal_spec:
            out["goal_spec"] = self.goal_spec
        if self.capabilities:
            out["required_capabilities"] = self.capabilities
        return out


class WorkerSpec(AgentSpec):
    """WorkerAgent spec —— 平台共享 worker 的完整定义。"""
    kind: Literal["worker"] = "worker"
    capability: str = Field(..., min_length=1, max_length=64,
                            description="capability slug；同时唯一标识平台中的 worker")
    capability_contract: dict = Field(...,
        description="advertises / version / side_effects 等；上线时 backward_compat 校验")
    needs_mcp: Optional[str] = Field(default=None,
                                     description="若该 worker 需要某个已注册 MCP server")

    # worker 默认强落地
    enable_thinking: bool = False
    max_iterations: int = Field(default=12, ge=1, le=50)
    temperature: float = 0.3

    @field_validator("capability")
    @classmethod
    def _check_capability(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(f"capability slug must match {_SLUG_RE.pattern}: got {v!r}")
        return v

    def to_extra_config(self) -> dict:
        out = dict(self.extra_config or {})
        out["capability_contract"] = self.capability_contract
        return out
