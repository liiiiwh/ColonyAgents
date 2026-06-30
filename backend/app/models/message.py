"""Message / ThreadAgentMemory / ThreadCompressionState（ADR-018 mission-only 终态）。

Session / SessionBranch / BranchAgentMemory 已随 step5/X 退役删除：会话的身份 = Mission(projects)
+ thread_key 字符串，不再有 session / branch 容器行。
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
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

# 跨方言 JSONB：PG 用原生 JSONB（支持 jsonb_set 原子更新 + ? 操作符）；SQLite 回落 JSON（测试用）
JSONB = JSON().with_variant(postgresql.JSONB(), "postgresql")

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Message(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "messages"

    # ADR-018 mission-only · 消息的真键 = (mission_id, thread_key)。
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    thread_key: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    # user / assistant / system / agent_log
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_compressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ThreadAgentMemory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """ADR-018 mission-only · thread 级压缩记忆，键 (mission_id, thread_key, agent_node_name)。
    压缩子系统唯一的记忆表（原 BranchAgentMemory 已退役）。"""

    __tablename__ = "thread_agent_memories"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    thread_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    agent_node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    memory_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    compressed_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_compressed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "mission_id", "thread_key", "agent_node_name", name="uq_thread_agent_memory"
        ),
    )


class ThreadCompressionState(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """ADR-018 step5/K · thread 级压缩状态，(mission_id, thread_key) 取代挂在 SessionBranch 上的
    compression_in_progress / compressed_up_to_at / 熔断字段 / thread 级 compression_config。

    一个 thread 一行（按需 lazy 创建）：
    - compression_in_progress：CAS 派发锁（UPDATE ... WHERE in_progress=false AND disabled=false）
    - compressed_up_to_at：水位线，所有 created_at <= 该时间的消息已被压缩或跳过
    - compression_disabled / consecutive_failures / last_error：连续失败 3 次熔断
    - compression_config：thread 级覆盖（最高优先级；NULL → super 级或平台级）
    """

    __tablename__ = "thread_compression_state"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    thread_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    compression_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    compression_disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_compression_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    compression_consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    compression_in_progress: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    compressed_up_to_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "mission_id", "thread_key", name="uq_thread_compression_state"
        ),
    )
