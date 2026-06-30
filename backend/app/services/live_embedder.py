"""真实 embedding 路由：根据 LLMModel 走 LiteLLM，给 knowledge_service 用。

启动期由 main.lifespan 调 `wire_to_knowledge_service()` 一次，
把 `set_embedder_by_model` 注入到 `knowledge_service`，此后所有 KB 的 index / search
会按 KB.embedding_model_id 走真实 provider。

设计：
- 每次 embed 起一个独立 AsyncSession 拿 model + provider；不依赖调用方传 db
  （`knowledge_service.embed(text, model_id)` 签名约束）
- model_id=None 时回退到 `DEFAULT_EMBEDDING_MODEL_ID` 环境变量；都没有时拿任意 enabled
  的 embedding model；再没有就用 hash fallback
- 失败时**不**抛异常 —— 知识库索引/搜索抛错会阻塞 Builder 流程，更糟。失败直接走
  hash fallback 并 logger.warning（语义降级但流程不断）
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.provider import LLMModel, LLMProvider

logger = logging.getLogger(__name__)


async def _hash_fallback(text: str) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    buf = (h * ((1536 // len(h)) + 1))[:1536]
    return [b / 255.0 for b in buf]


async def _resolve_default_embedding_model(db) -> LLMModel | None:
    """启动期 / 没指定 model_id 时按以下顺序找：
    1) settings.DEFAULT_EMBEDDING_MODEL_ID（env）—— 支持 UUID 或 `provider/model_id` 字符串
    2) 任意 enabled 的 embedding 类型 LLMModel
    """
    default_id = getattr(settings, "DEFAULT_EMBEDDING_MODEL_ID", None)
    if default_id:
        # 试 UUID
        try:
            mid = uuid.UUID(default_id) if isinstance(default_id, str) else default_id
            m = await db.get(LLMModel, mid)
            if m and m.is_enabled and m.model_type == "embedding":
                return m
        except (ValueError, TypeError):
            pass
        # 试 'provider/model_id' 字符串（如 'nebula/gemini-embedding-001'）
        if isinstance(default_id, str) and "/" in default_id:
            prov_name, model_name = default_id.split("/", 1)
            row = await db.execute(
                select(LLMModel)
                .join(LLMProvider, LLMModel.provider_id == LLMProvider.id)
                .where(
                    LLMProvider.name == prov_name,
                    LLMModel.model_id == model_name,
                    LLMModel.is_enabled.is_(True),
                    LLMModel.model_type == "embedding",
                )
                .limit(1)
            )
            m = row.scalar_one_or_none()
            if m:
                return m
        # 试裸 model_id（跨 provider 第一个命中）
        if isinstance(default_id, str):
            row = await db.execute(
                select(LLMModel).where(
                    LLMModel.model_id == default_id,
                    LLMModel.is_enabled.is_(True),
                    LLMModel.model_type == "embedding",
                ).limit(1)
            )
            m = row.scalar_one_or_none()
            if m:
                return m
    result = await db.execute(
        select(LLMModel)
        .where(LLMModel.is_enabled.is_(True), LLMModel.model_type == "embedding")
        .limit(1)
    )
    return result.scalar_one_or_none()


async def embed_by_model(text: str, model_id: uuid.UUID | None) -> list[float]:
    """生产 embedder：知识库 chunk / 查询走这里。"""
    import litellm

    from app.core.encryption import decrypt

    if not text:
        return await _hash_fallback("")

    try:
        async with AsyncSessionLocal() as db:
            model: LLMModel | None = None
            if model_id:
                model = await db.get(LLMModel, model_id)
            if model is None:
                model = await _resolve_default_embedding_model(db)
            if model is None:
                logger.warning(
                    "[live_embedder] 找不到可用 embedding LLMModel，回落 hash"
                )
                return await _hash_fallback(text)

            provider: LLMProvider | None = await db.get(LLMProvider, model.provider_id)
            if provider is None:
                logger.warning(
                    "[live_embedder] model=%s 的 provider=%s 不存在，回落 hash",
                    model.model_id, model.provider_id,
                )
                return await _hash_fallback(text)

            api_key = decrypt(provider.api_key)
            route = (
                f"openai/{model.model_id}"
                if provider.provider_type == "custom"
                else f"{provider.provider_type}/{model.model_id}"
            )

            kwargs: dict = {"model": route, "input": text, "api_key": api_key}
            if provider.base_url:
                kwargs["api_base"] = provider.base_url

            # 硬超时：embedding 是 KB 检索的依赖，慢于 15s 直接当失败兜底——
            # 否则 supervisor 卡 5 分钟（gemini-embedding-001 经代理时实测延迟），
            # 整个对话感觉死掉。失败走哈希兜底，KB 命中失效但流程能推进。
            try:
                resp = await asyncio.wait_for(litellm.aembedding(**kwargs), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "[live_embedder] aembedding 超时 15s（model=%s provider=%s）→ 哈希兜底",
                    model.model_id, provider.name,
                )
                return await _hash_fallback(text)
            # LiteLLM 返回 {data: [{embedding: [...]}], ...}
            data = (
                getattr(resp, "data", None)
                if not isinstance(resp, dict)
                else resp.get("data", [])
            )
            if not data:
                raise ValueError("aembedding 返回空 data")
            item = data[0]
            vec = (
                item.get("embedding")
                if isinstance(item, dict)
                else getattr(item, "embedding", None)
            )
            if not vec:
                raise ValueError("aembedding 第一条 data 缺 embedding 字段")
            vec = list(vec)
            # KB 列硬编码 1536 维（pgvector 列的 type 在表创建时固定）。
            # 实际 embedding 模型常见维度：text-embedding-3-small=1536 / -large=3072 /
            # gemini-embedding-001=3072 / ada-002=1536。**不等于 1536** 时强制裁剪 / 补 0，
            # 牺牲少量精度换 schema 兼容。后续应改用 per-KB 列维度（migration TODO）。
            target = 1536
            if len(vec) > target:
                vec = vec[:target]
            elif len(vec) < target:
                vec = vec + [0.0] * (target - len(vec))
            return vec

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[live_embedder] embed model_id=%s 失败 → hash fallback: %s",
            model_id, exc,
        )
        return await _hash_fallback(text)


def wire_to_knowledge_service() -> None:
    """启动期调用，把生产 embedder 注入 knowledge_service。"""
    from app.services import knowledge_service

    knowledge_service.set_embedder_by_model(embed_by_model)
    logger.info("[live_embedder] 已接管 knowledge_service.embed 路由")
