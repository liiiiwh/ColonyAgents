"""知识库服务：embedding + 分块 + 检索。

Phase 7 简化实现：
- 分块：按固定字符数切分（不依赖分词器，满足单测）
- Embedding：可通过 `set_embedder(fn)` 注入；默认使用 hash-based 占位以支持测试
- 检索：计算余弦相似度并按分值排序（SQLite fallback；pgvector 生产环境将自动走索引）

Phase 8 替换为 LiteLLM 真实 embedding + pgvector SQL 相似度排序。
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from math import sqrt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.models.provider import LLMModel, LLMProvider

logger = logging.getLogger(__name__)

# 两种签名：
# - 全局 fallback embedder：(text) -> vec
# - 按模型 embedder：(text, model_id) -> vec  当 KB 指定了 embedding_model_id 时用
EmbedFn = Callable[[str], Awaitable[list[float]]]
EmbedByModelFn = Callable[[str, uuid.UUID | None], Awaitable[list[float]]]


# ── Embedding 注入 ──
_embedder: EmbedFn | None = None
_embedder_by_model: EmbedByModelFn | None = None


def set_embedder(fn: EmbedFn | None) -> None:
    """老接口：注入全局 embedder。保留以兼容测试。"""
    global _embedder
    _embedder = fn


def set_embedder_by_model(fn: EmbedByModelFn | None) -> None:
    """新接口：按 KB 的 embedding_model_id 路由。生产环境用。"""
    global _embedder_by_model
    _embedder_by_model = fn


async def _default_embedder(text: str) -> list[float]:
    """哈希 → 1536 维浮点向量（非语义，仅供测试 / 确定性）。"""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    # 重复扩展到 1536 维
    buf = (h * ((1536 // len(h)) + 1))[:1536]
    return [b / 255.0 for b in buf]


async def embed(text: str, model_id: uuid.UUID | None = None) -> list[float]:
    """按模型路由的 embedding。优先级：

    1) `_embedder_by_model(text, model_id)` 注入了就走它（生产）
    2) `_embedder(text)` 老接口（旧测试）
    3) `_default_embedder` 哈希兜底（确定性 + 测试用）
    """
    if _embedder_by_model is not None:
        return await _embedder_by_model(text, model_id)
    if _embedder is not None:
        return await _embedder(text)
    return await _default_embedder(text)


# ── 分块 ──
def chunk_text(text: str, *, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    if not text:
        return []
    if chunk_size <= overlap:
        raise ValueError("chunk_size 必须大于 overlap")
    chunks: list[str] = []
    step = chunk_size - overlap
    for start in range(0, len(text), step):
        chunk = text[start : start + chunk_size]
        if chunk.strip():
            chunks.append(chunk)
        if start + chunk_size >= len(text):
            break
    return chunks


# ── KB CRUD ──
async def list_kbs(db: AsyncSession) -> Sequence[KnowledgeBase]:
    result = await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))
    return result.scalars().all()


async def get_kb(db: AsyncSession, kb_id: uuid.UUID) -> KnowledgeBase | None:
    result = await db.execute(
        select(KnowledgeBase)
        .options(selectinload(KnowledgeBase.documents))
        .where(KnowledgeBase.id == kb_id)
    )
    return result.scalar_one_or_none()


async def create_kb(
    db: AsyncSession,
    name: str,
    description: str,
    collection_name: str,
    embedding_model_id: uuid.UUID,
    created_by: uuid.UUID,
    *,
    mission_id: uuid.UUID | None = None,
    super_agent_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
    purpose: str = "",
) -> KnowledgeBase:
    model = await db.get(LLMModel, embedding_model_id)
    if not model:
        raise ValueError("embedding_model_id 指向的模型不存在")
    if model.model_type != "embedding":
        raise ValueError("选择的模型不是 embedding 类型")
    kb = KnowledgeBase(
        name=name,
        description=description,
        collection_name=collection_name,
        embedding_model_id=embedding_model_id,
        created_by=created_by,
        mission_id=mission_id,
        super_agent_id=super_agent_id,
        tags=tags or [],
        purpose=purpose,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def get_kb_by_super(db: AsyncSession, super_agent_id: uuid.UUID) -> KnowledgeBase | None:
    """ADR-023 S7 · 按 super 取共享 KB（同一 super 的所有 mission 共用一份）。取最早一条。"""
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.super_agent_id == super_agent_id)
        .order_by(KnowledgeBase.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_kb_by_project(db: AsyncSession, mission_id: uuid.UUID) -> KnowledgeBase | None:
    """ADR-023 S7 · 自动路由 KB：先按 mission 所属 super 取共享 KB（per-super），
    回退到旧的 mission 1:1 绑定。`knowledge_search/index` builtin 没拿到 kb_id 时走这里。"""
    from app.models.mission import Mission

    proj = await db.get(Mission, mission_id)
    if proj is not None and proj.supervisor_agent_id is not None:
        kb = await get_kb_by_super(db, proj.supervisor_agent_id)
        if kb is not None:
            return kb
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.mission_id == mission_id)
    )
    return result.scalar_one_or_none()


async def get_platform_kb(db: AsyncSession) -> KnowledgeBase | None:
    """v6 · 取平台级共享 KB（所有 super 都能 search；只能由 admin / Builder promote 入）。"""
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.scope == "platform").limit(1)
    )
    return result.scalar_one_or_none()


async def get_or_create_platform_kb(db: AsyncSession, *, created_by: uuid.UUID,
                                    embedding_model_id: uuid.UUID) -> KnowledgeBase:
    """v6 · 单例 platform KB；启动 seed 时调一次。"""
    existing = await get_platform_kb(db)
    if existing is not None:
        return existing
    kb = KnowledgeBase(
        name="platform-shared",
        description="平台共享经验 KB · v6（跨 project 可见；only Builder/admin promote 入）",
        collection_name="kb_platform_shared",
        embedding_model_id=embedding_model_id,
        created_by=created_by,
        scope="platform",
        mission_id=None,
        purpose="平台共享经验：跨 super 复用「rate limit / 风控规则 / 设计模板」等",
        tags=["platform", "shared"],
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def delete_kb(db: AsyncSession, kb: KnowledgeBase) -> None:
    await db.delete(kb)
    await db.commit()


# ── 文档索引 ──
async def index_document(
    db: AsyncSession,
    kb: KnowledgeBase,
    filename: str,
    content: str,
    *,
    s3_key: str | None = None,
) -> KnowledgeDocument:
    doc = KnowledgeDocument(
        kb_id=kb.id,
        filename=filename,
        s3_key=s3_key or f"kb/{kb.collection_name}/{filename}",
        status="indexing",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    chunks = chunk_text(content)
    for text in chunks:
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        # 幂等：已存在相同 hash 则跳过
        existing = await db.execute(
            select(KnowledgeChunk).where(
                KnowledgeChunk.kb_id == kb.id, KnowledgeChunk.chunk_hash == h
            )
        )
        if existing.scalar_one_or_none():
            continue
        vec = await embed(text, kb.embedding_model_id)
        db.add(
            KnowledgeChunk(
                kb_id=kb.id,
                document_id=doc.id,
                chunk_hash=h,
                content=text,
                embedding=vec,
                meta={"filename": filename},
            )
        )

    doc.chunk_count = len(chunks)
    doc.status = "indexed"
    await db.commit()
    await db.refresh(doc)
    return doc


async def delete_document(db: AsyncSession, doc: KnowledgeDocument) -> None:
    await db.delete(doc)
    await db.commit()


# ── 检索 ──
def _cosine(a, b) -> float:
    """余弦相似度。a/b 支持 list[float] 或 numpy.ndarray（pgvector 反序列化结果）。"""
    la = list(a) if a is not None else []
    lb = list(b) if b is not None else []
    if len(la) == 0 or len(lb) == 0:
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(la, lb, strict=False))
    na = sqrt(sum(float(x) * float(x) for x in la))
    nb = sqrt(sum(float(x) * float(x) for x in lb))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def search(db: AsyncSession, kb: KnowledgeBase, query: str, top_k: int = 5) -> list[dict]:
    """SQLite fallback：Python 侧计算余弦。

    Phase 8 引入 pgvector 原生 ORDER BY embedding <=> :query_vec LIMIT K。
    """
    q_vec = await embed(query, kb.embedding_model_id)
    stmt = select(KnowledgeChunk).where(KnowledgeChunk.kb_id == kb.id)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    scored = [
        {
            "chunk_id": r.id,
            "document_id": r.document_id,
            "score": _cosine(q_vec, r.embedding),
            "content": r.content,
            "meta": r.meta,
        }
        for r in rows
    ]
    scored.sort(key=lambda h: h["score"], reverse=True)
    return scored[:top_k]
