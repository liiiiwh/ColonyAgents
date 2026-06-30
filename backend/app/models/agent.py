"""Agent + 关联表（AgentSkill / AgentMCPServer / AgentAuxModel）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

# V7.5 · 跨方言 JSONB：PG 用原生 JSONB，SQLite 测试回落 JSON
# （原 raw `from ...postgresql import JSONB` 让 metrics_baseline 在 sqlite create_all 抛 visit_JSONB）
JSONB = JSON().with_variant(postgresql.JSONB(), "postgresql")

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    # super 身份：URL-safe slug + 人读显示名（kind='super' 才有意义）。
    # 路由 /mission/<super_slug>/<mission> 与「Super · <display_name>」用它，不再借 agent.name。
    # nullable：worker/系统对象可空；slug unique（NULL 不冲突）。
    slug: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # 功能分类，避免列表混乱；管理后台按 category 分组渲染。允许的值见
    # `app.schemas.agent.AgentCategory`：builder / installer / tester /
    # worker.web / worker.data / worker.io / worker.creative / utility / custom
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="custom", index=True
    )
    # NULL = use the platform default model (resolved at runtime by kind in
    # build_agent_executor). Lets platform agents be seeded before any LLM is configured;
    # they stay idle until a default model exists. An explicit UUID pins a specific model.
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("llm_models.id", ondelete="RESTRICT"),
        nullable=True,
    )
    soul_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    protocol_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    domain_memory_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    # 单次 LLM 调用的最大输出 token 数，传给 LiteLLM 的 `max_tokens`。
    # 默认 5000：足以覆盖绝大多数一次性交付物 Markdown；过高会让单次生成轻易耗尽 5 分钟 Worker
    # 预算（Nebula + Claude ~54 tok/s，14k token 需 260s），过低会频繁触发 length-stop 续写。
    # 当生成命中 length 限制时，ResilientChatLiteLLM 会自动续写（仅对纯文本；tool_call 截断
    # 会抛错让上层 Agent 分块写）。
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=30000)
    extra_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # ADR-015 · 平台系统对象（Builder Supervisor / builtin worker）：不可删除。
    # 前端隐删除钮，后端 delete 入口命中即 409。slug='builder' 自举集 seed 时置 True。
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # True = 该 Agent 的 workspace_write 结果被视为"交付物"：
    #        自动上传 S3，同节点覆盖写（仅保留最新一版，artifacts 数组里同 node 只存一条），
    #        在前端 Workspace 面板与交付物进度条中呈现。
    # False = 中间态/思考过程，仅保留 branch state，不上传 S3，不进前端 Workspace 面板。
    produces_deliverable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 【旧字段，保留兼容】每个 Agent 独立控制模型内置思考开关。
    # thinking_level 是新的权威控制（见下）；enable_thinking 仅在 thinking_level 缺省（旧数据/未传）
    # 时作回退：True→medium、False→off。
    enable_thinking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 思考档位（thinking_level）· 按 Agent 控制模型内置 reasoning/thinking 强度。
    # _build_llm 按当前模型家族把档位映射成各家具体参数（thinking_policy.py）：
    #   off    → 注入"最严格关闭"：claude thinking.disabled / gemini thinkingBudget=0(pro 128)
    #            / 其它 reasoning_effort=low（o-series 等无法真正关）
    #   low    → gemini thinkingBudget=512  / claude budget_tokens=2000  / reasoning_effort=low
    #   medium → gemini thinkingBudget=2048 / claude budget_tokens=8000  / reasoning_effort=medium
    #   high   → gemini thinkingBudget=8192 / claude budget_tokens=16000 / reasoning_effort=high
    # 默认 off（最省 token / 最快首 token）；Agent.extra_config 可继续覆盖。
    thinking_level: Mapped[str] = mapped_column(String(8), nullable=False, default="off")

    # 渲染契约 v0.4.18 起改为前端 autoDetect：按数据形状自动选 renderer，
    # Agent 想给中文标签 / 字段顺序就在输出 JSON 里塞 `_meta` 字段。
    # render_hint / render_config 列已删除（迁移 018）。

    # L2 自调优：version 完全派生于 agent_protocol_history（MAX(version) WHERE agent_id=...）
    # 不在 agents 表加列，避免对热表做 DDL；history 表是冷表 + APPEND only，没有冲突。

    # v3：Agent kind 区分 super / worker。每个 agent **必须**有 kind —— NULL 会让它在「Agents」页
    # 两个 tab（Super / Worker）都不可见（脏数据）。NOT NULL + 默认 'worker'，结构上杜绝 kind=NULL
    # （migration 077；038 当初加列时允许 NULL 兼容老数据）。
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="worker", default="worker", index=True,
    )
    # v3：worker capability 标签（如 "xhs_ops" / "data_analytics"）
    #     用于 super 调 invoke_worker("capability:xhs_ops", ...) 反查。
    #     super / builder / installer / tester 类一律 NULL。
    capability: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # ADR-018 D3 · 1:1 provenance：产出该 super 的 origin Builder mission（projects.id）。
    # super 自迭代 → 路由回此 mission（替代退役的 session.target_project_id 反查链）。
    # 仅 kind='super' 的产出物会被置；Builder/系统对象/worker 一律 NULL。
    # 迁移窗口内只双写不切路由（escalation 仍走旧链，step 5 再切）。
    built_by_mission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("missions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    skills: Mapped[list[AgentSkill]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    mcp_servers: Mapped[list[AgentMCPServer]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    aux_models: Mapped[list[AgentAuxModel]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class AgentSkill(Base, TimestampMixin):
    __tablename__ = "agent_skills"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    agent: Mapped[Agent] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship(lazy="joined")  # noqa: F821


class AgentMCPServer(Base, TimestampMixin):
    __tablename__ = "agent_mcp_servers"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), primary_key=True
    )
    # 为空 = 使用该 Server 的所有工具；否则仅暴露指定工具名
    tool_filter: Mapped[list | None] = mapped_column(JSON, nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="mcp_servers")
    mcp_server: Mapped[MCPServer] = relationship(lazy="joined")  # noqa: F821


class AgentAuxModel(Base, TimestampMixin):
    """Agent 绑定的辅助模型。主模型由 Agent.model_id 单独指定；
    辅助模型用于在 Agent 运行时通过 `invoke_aux_model` 工具按 role 调用
    （比如让 chat 模型调图像生成模型、embedding 模型等）。
    """

    __tablename__ = "agent_aux_models"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("llm_models.id", ondelete="CASCADE"), primary_key=True
    )
    # 用途角色：chat / vision / image / embedding / rerank / tts / stt / custom
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")
    # Agent 内唯一短名，供工具引用（如 "banana"、"primary-embedder"）
    alias: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 透传给 LiteLLM 的额外参数（如 image size、response_format）
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    agent: Mapped[Agent] = relationship(back_populates="aux_models")
    model: Mapped[LLMModel] = relationship(lazy="joined")  # noqa: F821


# ─────────────────────────── L2 自调优 ─────────────────────────────


class AgentProtocolHistory(Base, UUIDPrimaryKeyMixin):
    """Agent.protocol_md / soul_md 变更历史（L2 自调优审计链）。

    每次 `agent_update(protocol_md=...)` 或 `agent_protocol_apply()` 写一行：
    - factory_initial：seed 时第一版
    - supervisor_self_tune：项目 supervisor 通过 propose+apply 调优
    - builder_session：Builder Chat 在 EDIT 模式下改的
    - human_admin：admin UI 手改
    `rollback_of_version` 非空表示这是一次回滚（指向被回滚到的版本）。
    `metrics_baseline` 在 apply 时抓 5 条 quality_gate verdict 摘要，给 evaluate 用。

    保留策略（L2 §H5）：最近 20 版 + 永不删 factory_initial / human_admin。
    """

    __tablename__ = "agent_protocol_history"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    soul_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    applied_by_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    applied_by_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    trigger_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rollback_of_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics_baseline: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class AgentProtocolProposal(Base, UUIDPrimaryKeyMixin):
    """Supervisor 提议的 worker protocol 变更（pending → applied / rejected / expired）。

    设计：
    - `agent_protocol_propose` 只入此表（不改 agent），返回 proposal_id 给 supervisor
    - supervisor 必须 `request_approval` 把 diff_summary 推给用户
    - 用户通过 → supervisor 调 `agent_protocol_apply(proposal_id, confirmed=True)` 落库
    - `expires_at` 默认 24h；scheduler `expire_old_proposals` job 把过期的标 expired

    H4 并发锁：(agent_id) WHERE status='pending' 的 partial unique index
    防止同 agent 同时多条 pending。
    """

    __tablename__ = "agent_protocol_proposals"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # ADR-018 mission-only · proposer_session_id 已删（sessions 表退役；纯审计无读取）
    proposer_agent_node_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    proposed_soul_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_protocol_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff_summary: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    trigger_summary: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    expected_improvement: Mapped[str] = mapped_column(
        String(1000), nullable=False, default=""
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_history_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
