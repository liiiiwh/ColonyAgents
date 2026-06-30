"""ADR-016 · 默认模型解析。

优先级：system_settings(UI 选的 `default_{role}_model_id`) > env(`DEFAULT_{ROLE}_MODEL_ID`) > None。
把「选默认模型」从 env 写死搬到 UI，使任意 provider 的 OSS 用户都能开箱；不静默替换模型
（ADR-014）：都解析不到 → 返回 None，由调用方 fail loud。

model 引用支持三种写法：
- LLMModel 主键 UUID（UI 选模型后存的就是它）
- "provider_name/model_id"（env 习惯写法）
- "model_id"（跨 provider 取第一个匹配）
"""
from __future__ import annotations

import uuid as _uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import system_settings as _ss
from app.core.config import settings
from app.models.provider import LLMModel, LLMProvider

Role = Literal["supervisor", "agent"]

_ENV_KEY = {
    "supervisor": "DEFAULT_SUPERVISOR_MODEL_ID",
    "agent": "DEFAULT_AGENT_MODEL_ID",
}


async def _resolve_spec(db: AsyncSession, spec: str | None) -> LLMModel | None:
    if not spec:
        return None
    s = str(spec).strip().strip('"')
    if not s:
        return None
    # UUID（UI 选的主键）
    try:
        mid = _uuid.UUID(s)
    except (ValueError, TypeError):
        mid = None
    if mid is not None:
        return await db.get(LLMModel, mid)
    # provider_name/model_id
    if "/" in s:
        pname, mod = s.split("/", 1)
        r = await db.execute(
            select(LLMModel)
            .join(LLMProvider, LLMModel.provider_id == LLMProvider.id)
            .where(LLMProvider.name == pname, LLMModel.model_id == mod)
            .limit(1)
        )
        return r.scalar_one_or_none()
    # 裸 model_id
    r = await db.execute(select(LLMModel).where(LLMModel.model_id == s).limit(1))
    return r.scalar_one_or_none()


async def resolve_default_model(db: AsyncSession, role: Role) -> LLMModel | None:
    """按 system_settings(UI) > env 解析默认模型；都无 → None（调用方 fail loud）。"""
    ss_val = await _ss.get(db, f"default_{role}_model_id", None)
    m = await _resolve_spec(db, ss_val)
    if m is not None:
        return m
    env_val = getattr(settings, _ENV_KEY[role], None)
    return await _resolve_spec(db, env_val)


# 续接① · 默认模型可见性：embedding 无 env 写法，只走 system_settings。
_DESCRIBE_ROLES = ("supervisor", "agent", "embedding")
_SS_KEY = {r: f"default_{r}_model_id" for r in _DESCRIBE_ROLES}


async def _label_for(db: AsyncSession, m: LLMModel) -> str:
    """provider_name/model_id 展示名（绝不裸 uuid）。"""
    prov = await db.get(LLMProvider, m.provider_id)
    return f"{(prov.name if prov else '?')}/{m.model_id}"


async def describe_default_model(db: AsyncSession, role: str) -> dict:
    """解析单个 role 的默认模型 + 来源，供设置页显示/编辑。

    返回 {role, spec, source, model_id, label}：
    - source: 'system_settings'（UI/设置页存的）| 'env'（.env 写死）| 'unresolved'（有 spec 但解析不到）| 'none'
    - model_id/label: 解析到的 LLMModel 主键 与 provider/model_id 展示名；解析不到则 None
    """
    ss_val = await _ss.get(db, _SS_KEY[role], None)
    env_val = getattr(settings, _ENV_KEY[role], None) if role in _ENV_KEY else None
    if ss_val:
        spec, source = ss_val, "system_settings"
    elif env_val:
        spec, source = env_val, "env"
    else:
        spec, source = None, "none"
    m = await _resolve_spec(db, spec) if spec else None
    if spec and m is None:
        source = "unresolved"
    return {
        "role": role,
        "spec": spec,
        "source": source,
        "model_id": str(m.id) if m is not None else None,
        "label": (await _label_for(db, m)) if m is not None else None,
    }


async def describe_default_models(db: AsyncSession) -> list[dict]:
    """三个默认模型(supervisor/agent/embedding)的有效值视图。"""
    return [await describe_default_model(db, r) for r in _DESCRIBE_ROLES]
