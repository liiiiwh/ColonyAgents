"""知识库 schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeBaseBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    collection_name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_]*$")
    embedding_model_id: uuid.UUID


class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)


class KnowledgeBasePublic(KnowledgeBaseBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class DocumentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    filename: str
    s3_key: str
    chunk_count: int
    status: Literal["pending", "indexing", "indexed", "failed"]
    created_at: datetime


class IndexDocumentRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, description="文本内容（UTF-8）；二进制文档请先转文本")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID | None
    score: float
    content: str
    meta: dict


class SearchResponse(BaseModel):
    hits: list[SearchHit]
