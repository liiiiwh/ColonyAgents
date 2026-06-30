"""知识库模型。

Phase 7：向量字段使用 pgvector（PostgreSQL 独有）。
SQLite 测试环境下用 `_VectorCompat` 回退为 JSON 存储，保证单测可运行。
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class _VectorCompat(TypeDecorator):
    """跨方言的向量类型。

    - PostgreSQL：委托给 pgvector.sqlalchemy.Vector
    - 其他方言（SQLite 测试）：使用 JSON 列（不支持相似度查询）
    """

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int = 1536):
        self.dim = dim
        super().__init__()

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())


class KnowledgeBase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    collection_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    embedding_model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("llm_models.id", ondelete="RESTRICT"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # ── 项目级 KB（每个 Mission 自动创建一条；NULL = 管理员手动建的独立 KB） ──
    # ondelete=CASCADE：删项目自动删它的 KB（含 chunks / documents 级联）
    # uq_kb_project：一个 project 至多一条 KB（DB 强约束）
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
        index=True,
    )
    # ADR-023 S7 · per-super 共享 KB：同一 super 的所有 mission 共用一份。新逻辑按 super_agent_id
    # 取/建（_ensure_super_kb 幂等）；mission_id 保留作旧 1:1 数据兼容（回填后不再强绑）。
    super_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Builder 经验学习用的元信息；前端管理页可编辑
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    purpose: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    # v6 · KB scope：'project' (默认；归属某 project) / 'platform' (跨 project 共享)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="project")

    documents: Mapped[list[KnowledgeDocument]] = relationship(
        back_populates="kb",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class KnowledgeDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "knowledge_documents"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # pending / indexing / indexed / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    kb: Mapped[KnowledgeBase] = relationship(back_populates="documents")


class KnowledgeChunk(Base, UUIDPrimaryKeyMixin):
    """向量化后的文本片段。"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("kb_id", "chunk_hash", name="uq_chunks_hash"),)

    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=True
    )
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(_VectorCompat(1536), nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
