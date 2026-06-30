"""知识库 API。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import AdminUser, DBSession
from app.models.knowledge import KnowledgeBase, KnowledgeDocument
from app.schemas.knowledge import (
    DocumentPublic,
    IndexDocumentRequest,
    KnowledgeBaseCreate,
    KnowledgeBasePublic,
    KnowledgeBaseUpdate,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from app.services import knowledge_service

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeBasePublic])
async def list_kbs(_: AdminUser, db: DBSession) -> list[KnowledgeBasePublic]:
    items = await knowledge_service.list_kbs(db)
    return [KnowledgeBasePublic.model_validate(i) for i in items]


@router.post("", response_model=KnowledgeBasePublic, status_code=status.HTTP_201_CREATED)
async def create_kb(
    payload: KnowledgeBaseCreate, admin: AdminUser, db: DBSession
) -> KnowledgeBasePublic:
    exists = await db.execute(
        select(KnowledgeBase).where(
            (KnowledgeBase.name == payload.name)
            | (KnowledgeBase.collection_name == payload.collection_name)
        )
    )
    if exists.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="name 或 collection_name 已存在")
    try:
        kb = await knowledge_service.create_kb(
            db,
            name=payload.name,
            description=payload.description,
            collection_name=payload.collection_name,
            embedding_model_id=payload.embedding_model_id,
            created_by=admin.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return KnowledgeBasePublic.model_validate(kb)


@router.get("/{kb_id}", response_model=KnowledgeBasePublic)
async def get_kb(kb_id: uuid.UUID, _: AdminUser, db: DBSession) -> KnowledgeBasePublic:
    kb = await knowledge_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    return KnowledgeBasePublic.model_validate(kb)


@router.put("/{kb_id}", response_model=KnowledgeBasePublic)
async def update_kb(
    kb_id: uuid.UUID, payload: KnowledgeBaseUpdate, _: AdminUser, db: DBSession
) -> KnowledgeBasePublic:
    kb = await knowledge_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(kb, field, value)
    await db.commit()
    await db.refresh(kb)
    return KnowledgeBasePublic.model_validate(kb)


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kb(kb_id: uuid.UUID, _: AdminUser, db: DBSession) -> None:
    kb = await knowledge_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    await knowledge_service.delete_kb(db, kb)


# ── Documents ──
@router.get("/{kb_id}/documents", response_model=list[DocumentPublic])
async def list_documents(kb_id: uuid.UUID, _: AdminUser, db: DBSession) -> list[DocumentPublic]:
    kb = await knowledge_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    return [DocumentPublic.model_validate(d) for d in kb.documents]


@router.post(
    "/{kb_id}/documents",
    response_model=DocumentPublic,
    status_code=status.HTTP_201_CREATED,
)
async def index_document(
    kb_id: uuid.UUID,
    payload: IndexDocumentRequest,
    _: AdminUser,
    db: DBSession,
) -> DocumentPublic:
    kb = await knowledge_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    doc = await knowledge_service.index_document(db, kb, payload.filename, payload.content)
    return DocumentPublic.model_validate(doc)


@router.delete("/{kb_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(kb_id: uuid.UUID, doc_id: uuid.UUID, _: AdminUser, db: DBSession) -> None:
    doc = await db.get(KnowledgeDocument, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="文档不存在")
    await knowledge_service.delete_document(db, doc)


# ── 检索 ──
@router.post("/{kb_id}/search", response_model=SearchResponse)
async def search(
    kb_id: uuid.UUID, payload: SearchRequest, _: AdminUser, db: DBSession
) -> SearchResponse:
    kb = await knowledge_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    hits = await knowledge_service.search(db, kb, payload.query, payload.top_k)
    return SearchResponse(hits=[SearchHit(**h) for h in hits])
