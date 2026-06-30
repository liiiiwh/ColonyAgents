"""LLM 提供商与模型。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    pass


class LLMProvider(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """LLM 提供商配置。API Key 使用 Fernet 加密后存储在 `api_key` 字段。"""

    __tablename__ = "llm_providers"

    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Fernet 加密后的密文
    api_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extra_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    models: Mapped[list[LLMModel]] = relationship(
        back_populates="provider",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class LLMModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """LLM 模型（chat / embedding / completion）。"""

    __tablename__ = "llm_models"
    __table_args__ = (UniqueConstraint("provider_id", "model_id", name="uq_model_per_provider"),)

    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("llm_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # chat / embedding / completion
    model_type: Mapped[str] = mapped_column(String(16), nullable=False, default="chat")
    context_window: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    supports_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_function_calling: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    provider: Mapped[LLMProvider] = relationship(back_populates="models")
