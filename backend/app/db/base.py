"""SQLAlchemy declarative base + 通用混入。

所有模型通过 `from app.db.base import Base` 继承。
Alembic autogenerate 需要 import 所有模型，因此 `app/db/base_all.py`
再集中 re-export（避免循环依赖）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

_TYPE_ANNOTATION_MAP: dict[Any, Any] = {}


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    # 提供 type_annotation_map 可扩展点（当前留空）
    type_annotation_map = _TYPE_ANNOTATION_MAP

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        # 将 CamelCase 类名转为 snake_case 表名（简单实现）
        name = cls.__name__
        result: list[str] = []
        for i, ch in enumerate(name):
            if i > 0 and ch.isupper():
                result.append("_")
            result.append(ch.lower())
        return "".join(result)


class UUIDPrimaryKeyMixin:
    """统一 UUID 主键（使用 SQLAlchemy 跨方言 Uuid 类型）。"""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """created_at / updated_at 时间戳。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
