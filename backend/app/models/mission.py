"""Mission 模型。

Colony 是共享工作台：所有登录用户都能看到同一份 projects，无 ACL 过滤。
仅保留 `created_by` 作为审计字段。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Mission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "missions"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    # 元数据状态：draft / active / archived（不代表运行态）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    # M1：运行态状态机；与 status 正交（active 项目可能是 stopped/running/...）
    # 取值：stopped / starting / running / stopping / error
    runtime_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="stopped", index=True
    )
    supervisor_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    # 默认全自动·完全授权：新建 mission 默认 auto_approve=True（routine 审批自动通过，
    # 真正需要真人的门（force_human：扫码/付款/「停到 X」）仍照常拦，见 domain/auto_approve）。
    # 用户可在工作台 AutoApproveToggle 按 mission 关掉。
    auto_approve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # ADR-015 · 平台系统对象（Builder Mission slug='builder'）：不可删除。
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 默认 300000 ≈ 30 万 token，对应**整个组装 context**（系统提示 + memory_md +
    # workspace + 未压缩对话）的上限，并非只是消息部分。
    # 运维可在 .env 配 DEFAULT_CONTEXT_COMPRESSION_THRESHOLD 统一调整；
    # 单个 project 可在 admin/projects/[id] 页面手工覆写。
    # 这里 ORM default 保留字面量避免早绑定 settings。
    context_compression_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300_000
    )
    workflow_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # ADR-027 · workspace JSON：质量门 verdict 历史 / qgate counter 等过程态，按 worker
    # capability label 作 key（不再与已退役的 mission_nodes 行关联）。一个 Mission 一份；
    # workspace_version 走乐观并发 CAS。交付物本身只活在 S3 + data-artifact 事件 + worker thread。
    workspace: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    workspace_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # v3 §B5：super 暂停 / 恢复状态机
    # 取值：stopped / running / paused_waiting_capability / error
    # 与 runtime_status 平行；lifecycle_status 是新模型的真相源（scheduler / api 看这个）
    lifecycle_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="stopped"
    )
    paused_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # R21 super 级压缩配置（可选；覆盖平台默认；不覆盖则 fallback 到 system_settings）
    # 字段：{threshold_tokens?, keep_recent?, target_ratio?}
    compression_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    run_state: Mapped[MissionRunState | None] = relationship(
        back_populates="mission",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )


class MissionRunState(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """M1：Mission 运行时态持久化。

    与 `projects.runtime_status` 配对：projects 上的 `runtime_status` 是真相，
    本表存额外的运行细节（启动 / 停止时间 / 最后心跳 / 错误信息 / 当前步骤）。

    一个 Mission 至多一行（unique constraint on mission_id）。Daemon 启动 / 心跳 /
    停止 / 报错时都会更新这里。后端启动期的 reconcile 也读本表判断「上一次跑到一半
    被 SIGKILL 的 project」并把它们标成 error。
    """

    __tablename__ = "mission_run_state"
    __table_args__ = (
        UniqueConstraint("mission_id", name="uq_mission_run_state_mission"),
    )

    mission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 与 projects.runtime_status 保持一致（冗余但方便单点查询）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="stopped")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # daemon 协程每 N 秒 update_at 这里；reconcile 判断「卡死 / 进程死了」靠它
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # daemon 当前在做什么（idle / heartbeat / run_once / ...），仅给前端展示
    # NB: 原 String(64) 在 paused_reason 等长文案下溢出（StringDataRightTruncationError）→ 放宽到 255
    current_step: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 总运行次数（run_once 调用次数 + 调度触发次数；M2 后会增长）
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    mission: Mapped[Mission] = relationship(back_populates="run_state")


class MissionSchedule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """M2：Mission 触发计划。

    一个 Mission 可以挂多条 schedule，APScheduler 启动期把 enabled=True 的
    rehydrate 到内存 scheduler。Scheduler 触发时调 `mission_daemon.run_once`。

    kind / expr 语义：
    - cron     : expr 是 5 段 cron 表达式（"分 时 日 月 周"，APScheduler CronTrigger 解析）
    - interval : expr 是带单位的间隔（"30s" / "5m" / "2h" / "1d"）
    - event    : expr 是事件名（webhook 触发用，scheduler 不主动驱动；POST
                 /api/missions/{id}/events/{name} 时手动 fire）
    """

    __tablename__ = "mission_schedule"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # cron / interval / event
    expr: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_template: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_fire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fire_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    mission: Mapped[Mission] = relationship()


class MissionAgentMemory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """M3：项目级 Agent 记忆。

    与 `branch_agent_memories` 平行：branch 维度的记忆用于 Orchestrator 多次对话演化；
    project 维度的记忆用于 daemon 长期运行的 Agent。Schema 结构一致，只是 FK 不同。

    一个 project + agent_node_name 最多一行。
    """

    __tablename__ = "mission_agent_memory"
    __table_args__ = (
        UniqueConstraint(
            "mission_id", "agent_node_name", name="uq_mission_agent_memory"
        ),
    )

    mission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    memory_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    compressed_message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_compressed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ─────────────────────────── L3 升级到 Builder ─────────────────────


class MissionEscalation(Base, UUIDPrimaryKeyMixin):
    """worker-project supervisor 主动向 origin Builder Chat 发的升级信封。

    设计：
    - quota 3/天/项目（workflow_config.escalation_quota_remaining；夜间 reset）
    - fingerprint = sha256(category + summary_normalized + worker_id)；
      unique(mission_id, fingerprint, date) 让同根因每天只 1 行
    - status 状态机：pending → delivered → acted | dismissed | superseded
    - 投递走 escalation_dispatcher.py 异步任务，给 origin session current branch
      写一条 role=system 消息 + 推一条 wechat 通知；**不**自动唤醒 Builder LLM
    """

    __tablename__ = "mission_escalations"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warn")
    summary: Mapped[str] = mapped_column(String(280), nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    proposed_change: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ADR-018 mission-only · target_session_id 已删（sessions 表退役；escalation 用 origin_session_id meta）
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
