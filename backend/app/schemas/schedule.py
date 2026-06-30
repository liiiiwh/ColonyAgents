"""M2：MissionSchedule Pydantic schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ScheduleKind = Literal["cron", "interval", "event"]


def _validate_expr(kind: str, expr: str) -> None:
    """跨方言验证 expr 合法性。

    注意：所有 raise ValueError 时不要带 `from exc`，否则 Pydantic 把原始 exception
    塞进 ctx 字段，FastAPI 422 序列化时炸 (ValueError 不是 JSON serializable)。
    """
    expr = expr.strip()
    if not expr:
        raise ValueError("expr 不能为空")
    if kind == "cron":
        # 仅支持 5 段 cron（"分 时 日 月 周"），与 APScheduler CronTrigger 一致
        from apscheduler.triggers.cron import CronTrigger  # 局部 import 避免循环

        try:
            CronTrigger.from_crontab(expr)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"cron 表达式非法：{exc}")
    elif kind == "interval":
        # 单位 s/m/h/d，纯整数（"30s" / "5m" / "2h" / "1d"）
        import re

        m = re.fullmatch(r"(\d+)([smhd])", expr)
        if not m:
            raise ValueError(
                "interval 必须形如 '30s' / '5m' / '2h' / '1d'（整数 + s/m/h/d）"
            )
        n = int(m.group(1))
        if n <= 0:
            raise ValueError("interval 数值必须为正")
    elif kind == "event":
        import re

        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", expr):
            raise ValueError(
                "event 名称必须是小写字母 / 数字 / _-，且以字母数字开头"
            )
    else:
        raise ValueError(f"未知 schedule kind：{kind}")


class ScheduleBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: ScheduleKind
    expr: str = Field(min_length=1, max_length=128)
    payload_template: dict = Field(default_factory=dict)
    enabled: bool = True


class ScheduleCreate(ScheduleBase):
    """expr 校验由 API 层用 try/except _validate_expr 完成，避免
    Pydantic v2 把原 ValueError 塞进 422 ctx 而触发 JSON 序列化失败。"""


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    kind: ScheduleKind | None = None
    expr: str | None = Field(default=None, min_length=1, max_length=128)
    payload_template: dict | None = None
    enabled: bool | None = None


class SchedulePublic(ScheduleBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mission_id: uuid.UUID
    last_fired_at: datetime | None = None
    next_fire_at: datetime | None = None
    last_error: str | None = None
    fire_count: int = 0
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class EventFireRequest(BaseModel):
    """POST /api/missions/{id}/events/{event_name} 的 body。"""

    payload: dict = Field(default_factory=dict)
