"""R4-1 · LlmResolver · 解析平台默认 chat LLM（修分层倒置）。

之前 _resolve_default_chat_llm 住在 api/preview_chat.py，被 compression_service /
mission_test_runner / wechat_intent 三个 service local-import（API←service 倒置 +
循环依赖 workaround）。搬到 service 层，方向归正。

顺带复用 R3 的 provider_router（原函数内联重复了 route + streaming 逻辑）。

公共接口：
- resolve_model_for_default_spec(db, spec) → LLMModel  （spec 解析，可单测）
- resolve_default_chat_llm(db) → ResilientChatLiteLLM  （组装可调用 LLM）
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.provider import LLMModel, LLMProvider


async def resolve_model_for_default_spec(db: AsyncSession, spec: str) -> LLMModel:
    """把 `provider_name/model_id` 或裸 `model_id` 解析成唯一 LLMModel。

    - 'provider/model' → 按 provider 名 + model_id 精确定位
    - 裸 'model_id'     → 唯一即取；多 provider 重名报错要求消歧
    - 找不到            → 报错
    """
    model: LLMModel | None = None
    if "/" in spec:
        provider_name, model_id = spec.split("/", 1)
        model = (
            await db.execute(
                select(LLMModel)
                .join(LLMProvider, LLMProvider.id == LLMModel.provider_id)
                .where(LLMModel.model_id == model_id)
                .where(LLMProvider.name == provider_name)
            )
        ).scalar_one_or_none()
    else:
        rows = (
            await db.execute(select(LLMModel).where(LLMModel.model_id == spec))
        ).scalars().all()
        if len(rows) == 1:
            model = rows[0]
        elif len(rows) > 1:
            raise RuntimeError(
                f"DEFAULT_AGENT_MODEL_ID={spec!r} 在多个 provider 下重名，"
                "请用 `provider_name/model_id` 格式消歧"
            )
    if not model:
        raise RuntimeError(f"DEFAULT_AGENT_MODEL_ID={spec!r} 未找到对应 LLMModel 行")
    return model


async def resolve_default_chat_llm(db: AsyncSession) -> Any:
    """解析 settings.DEFAULT_AGENT_MODEL_ID → ResilientChatLiteLLM（闲聊用，参数保守）。"""
    from app.core.encryption import decrypt
    from app.services.resilient_llm import ResilientChatLiteLLM
    from app.domain.llm.provider_router import resolve_route, should_stream

    model = await resolve_model_for_default_spec(db, settings.DEFAULT_AGENT_MODEL_ID)
    provider = await db.get(LLMProvider, model.provider_id)
    if not provider:
        raise RuntimeError(f"Provider {model.provider_id} 不存在")

    route = resolve_route(provider.provider_type, model.model_id)
    use_streaming = should_stream(provider.provider_type, model.model_id)

    kwargs: dict[str, Any] = {
        "model": route,
        "api_key": decrypt(provider.api_key),
        "temperature": 0.7,
        "max_tokens": 1024,
        "streaming": use_streaming,
    }
    if provider.base_url:
        if route.startswith("openai/"):
            base = provider.base_url.rstrip("/")
            kwargs["api_base"] = base if base.endswith("/v1") else base + "/v1"
        else:
            kwargs["api_base"] = provider.base_url
    return ResilientChatLiteLLM(**kwargs)
