"""knowledge bases + documents + chunks

Revision ID: 007_knowledge
Revises: 006_sessions
Create Date: 2026-04-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007_knowledge"
down_revision: str | None = "006_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("collection_name", sa.String(length=128), nullable=False),
        sa.Column("embedding_model_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["embedding_model_id"], ["llm_models.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("name", name="uq_kb_name"),
        sa.UniqueConstraint("collection_name", name="uq_kb_collection"),
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=256), nullable=False),
        sa.Column("s3_key", sa.String(length=512), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_knowledge_documents_kb_id", "knowledge_documents", ["kb_id"]
    )

    # chunks 表 embedding 字段在生产 (PostgreSQL) 使用 vector(1536)，在迁移脚本中通过 CREATE EXTENSION
    # 001 已启用。此处用 JSON 作为抽象层，由 SQLAlchemy 的 _VectorCompat 类型在 PG 上自动替换。
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_hash", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("kb_id", "chunk_hash", name="uq_chunks_hash"),
    )
    op.create_index("ix_knowledge_chunks_kb_id", "knowledge_chunks", ["kb_id"])

    # PostgreSQL 专属：将 embedding 字段改为 vector(1536) 并建立 ivfflat 索引
    # 注意：pgvector 不支持 json→vector 直接 cast；因新建表为空，DROP + ADD 最干净
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE knowledge_chunks DROP COLUMN embedding")
        op.execute(
            "ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1536) NOT NULL"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding "
            "ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_kb_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_documents_kb_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_bases")
