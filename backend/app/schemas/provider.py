"""LLM Provider / Model Pydantic schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderType = Literal[
    "openai", "anthropic", "azure", "ollama", "deepseek", "gemini", "custom",
    # 已搬过来 aliyun (dashscope) + volcengine (doubao/seedance/seedream) provider 路由
    "aliyun", "dashscope", "volcengine",
]
# image / video 是新加的（_infer_model_type 会把 seedream/flux/seedance 等分到这两类）
ModelType = Literal["chat", "embedding", "completion", "image", "video"]


# ── Provider ──
class ProviderBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider_type: ProviderType
    base_url: str | None = None
    extra_config: dict = Field(default_factory=dict)
    is_enabled: bool = True


class ProviderCreate(ProviderBase):
    api_key: str = Field(
        min_length=1, max_length=2048, description="明文 API Key；入库前会 Fernet 加密"
    )


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    provider_type: ProviderType | None = None
    api_key: str | None = Field(default=None, description="传入则替换现有 key，留空保持不变")
    base_url: str | None = None
    extra_config: dict | None = None
    is_enabled: bool | None = None


class ProviderPublic(ProviderBase):
    """响应体不包含 api_key（仅返回 has_api_key 标志）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    has_api_key: bool = True
    created_at: datetime
    updated_at: datetime


# ── Model ──
class ModelBase(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    model_type: ModelType = "chat"
    context_window: int = 0
    supports_vision: bool = False
    supports_function_calling: bool = False
    is_enabled: bool = True


class ModelUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    model_type: ModelType | None = None
    context_window: int | None = None
    supports_vision: bool | None = None
    supports_function_calling: bool | None = None
    is_enabled: bool | None = None


class ModelPublic(ModelBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ModelListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    model_id: str
    display_name: str
    model_type: ModelType
    is_enabled: bool


class SyncModelsResponse(BaseModel):
    synced: int
    models: list[ModelPublic]
