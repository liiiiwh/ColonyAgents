"""LLM 提供商 API。管理员才能访问。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import AdminUser, DBSession
from app.models.provider import LLMModel as LLMModelORM
from app.models.provider import LLMProvider
from app.schemas.provider import (
    ModelBase,
    ModelListItem,
    ModelPublic,
    ModelUpdate,
    ProviderCreate,
    ProviderPublic,
    ProviderUpdate,
    SyncModelsResponse,
)
from app.services import provider_service
from app.services.provider_service import ProviderSyncError

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _to_public(p: LLMProvider) -> ProviderPublic:
    return ProviderPublic.model_validate(
        {
            "id": p.id,
            "name": p.name,
            "provider_type": p.provider_type,
            "base_url": p.base_url,
            "extra_config": p.extra_config,
            "is_enabled": p.is_enabled,
            "has_api_key": bool(p.api_key),
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }
    )


@router.get("", response_model=list[ProviderPublic])
async def list_providers(_: AdminUser, db: DBSession) -> list[ProviderPublic]:
    items = await provider_service.list_providers(db)
    return [_to_public(p) for p in items]


@router.post("", response_model=ProviderPublic, status_code=status.HTTP_201_CREATED)
async def create_provider(payload: ProviderCreate, _: AdminUser, db: DBSession) -> ProviderPublic:
    existing = await db.execute(select(LLMProvider).where(LLMProvider.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="同名 provider 已存在")
    provider = await provider_service.create_provider(db, payload)
    return _to_public(provider)


@router.get("/{provider_id}", response_model=ProviderPublic)
async def get_provider(provider_id: uuid.UUID, _: AdminUser, db: DBSession) -> ProviderPublic:
    provider = await provider_service.get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="provider 不存在")
    return _to_public(provider)


@router.put("/{provider_id}", response_model=ProviderPublic)
async def update_provider(
    provider_id: uuid.UUID, payload: ProviderUpdate, _: AdminUser, db: DBSession
) -> ProviderPublic:
    provider = await provider_service.get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="provider 不存在")
    updated = await provider_service.update_provider(db, provider, payload)
    return _to_public(updated)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: uuid.UUID, _: AdminUser, db: DBSession) -> None:
    provider = await provider_service.get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="provider 不存在")
    await provider_service.delete_provider(db, provider)


@router.post(
    "/{provider_id}/sync-models",
    response_model=SyncModelsResponse,
)
async def sync_models(provider_id: uuid.UUID, _: AdminUser, db: DBSession) -> SyncModelsResponse:
    provider = await provider_service.get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="provider 不存在")
    try:
        models = await provider_service.sync_provider_models(db, provider)
    except ProviderSyncError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"提供商同步失败：{exc}",
        ) from exc
    return SyncModelsResponse(
        synced=len(models),
        models=[ModelPublic.model_validate(m) for m in models],
    )


@router.get("/{provider_id}/models", response_model=list[ModelListItem])
async def list_models(provider_id: uuid.UUID, _: AdminUser, db: DBSession) -> list[ModelListItem]:
    provider = await provider_service.get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="provider 不存在")
    items = await provider_service.list_models(db, provider_id)
    return [ModelListItem.model_validate(m) for m in items]


@router.post(
    "/{provider_id}/models",
    response_model=ModelPublic,
    status_code=status.HTTP_201_CREATED,
)
async def add_model(
    provider_id: uuid.UUID,
    payload: ModelBase,
    _: AdminUser,
    db: DBSession,
) -> ModelPublic:
    """手动添加模型（用于 custom provider 或 sync 失败后的补救）。"""
    provider = await provider_service.get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="provider 不存在")
    try:
        model = await provider_service.add_model(db, provider, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ModelPublic.model_validate(model)


@router.patch("/{provider_id}/models/{model_id}", response_model=ModelPublic)
async def update_model(
    provider_id: uuid.UUID,
    model_id: uuid.UUID,
    payload: ModelUpdate,
    _: AdminUser,
    db: DBSession,
) -> ModelPublic:
    result = await db.execute(
        select(LLMModelORM).where(
            LLMModelORM.id == model_id,
            LLMModelORM.provider_id == provider_id,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="model 不存在")
    updated = await provider_service.update_model(db, model, payload.model_dump(exclude_unset=True))
    return ModelPublic.model_validate(updated)
