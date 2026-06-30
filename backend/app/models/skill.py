"""Skill（instruction / tool_builtin）与 MCP Server 模型 + M6 ClawHub 安装记录。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Skill(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Skill：指令型（SKILL.md 注入 System Prompt）或内置工具型。"""

    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # Optional English description. When both description (default/zh) and description_en
    # are non-empty, the list page shows the one matching the current UI language.
    description_en: Mapped[str | None] = mapped_column(String(512), nullable=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")
    # 功能分类，与 Agent.category 同枚举；管理后台按 category 分组渲染。
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="custom", index=True
    )
    # instruction / tool_builtin
    skill_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # SKILL.md 内容（含 YAML frontmatter），或 tool_builtin 的说明
    content_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # tool_builtin 专用：内置工具注册表中的 slug
    builtin_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 可配参数 JSON Schema（前端表单生成用）
    config_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 内置 Skill 不可删除
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # v6 · SkillScope / SkillIntent (CONTEXT.md > "Skill 维度")
    # scope ∈ {super, worker, builder, all}（auto-bind 用：worker 不绑 super-only）
    # intent ∈ {dispatch, memory, approval, escalation, io, knowledge, observation}
    # 都 nullable=True 兼容老数据；新代码注册 skill 时填上让 auto-bind 走 declarative
    scope: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)


class RemoteSkillInstall(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """M6：从 ClawHub 安装的远程 Skill 记录。

    一行 = 一个特定 slug+version 的安装；本表是「安装的物理状态真相」。
    对应在 `skills` 表里有一条 mirror row（is_builtin=False, builtin_ref=remote install id），
    Agent 通过那条 mirror 绑定 / 取消绑定，调用时再回查本表拿 install_dir / wrapper。
    """

    __tablename__ = "remote_skill_install"
    __table_args__ = (
        UniqueConstraint(
            "clawhub_slug", "clawhub_version", name="uq_remote_skill_slug_version"
        ),
    )

    # 关联到的 project（null=全局安装；Skill Browser 也走全局）
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    clawhub_slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    clawhub_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # python / node / nextjs / mcp-server / static-instruction
    runtime_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    install_dir: Mapped[str] = mapped_column(String(512), nullable=False)
    entrypoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    python_wrapper_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    capability_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    security_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # 关联到本地 skills 表的镜像行（让 Agent 能 bind 它）
    local_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MCPServer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """MCP Server（stdio 或 http transport）。"""

    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # stdio / http
    server_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # stdio 模式：command 数组，如 ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"]
    command: Mapped[list | None] = mapped_column(JSON, nullable=True)
    env_vars: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # http 模式
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 拉起本地 MCP server 的命令（如 ["/path/to/xhs-mcp", "--port", "18060"]）。
    # 由 mcp_server_restart skill 在 worker 探测到 server 挂了时调用。
    # http 模式才用得到（stdio 模式 langchain-mcp-adapters 自带 spawn）；为空就不能自动重启。
    startup_command: Mapped[list | None] = mapped_column(JSON, nullable=True)
    startup_cwd: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # ADR-010 R1 · readiness manifest（{deployment, requirements:[{id,kind,probe,remediation}]}）。
    # Builder 装/接 MCP 时自动生成；ensure_ready resolver 据此探针 + 派发补救。
    readiness_manifest: Mapped[dict | None] = mapped_column(JSON, nullable=True)
