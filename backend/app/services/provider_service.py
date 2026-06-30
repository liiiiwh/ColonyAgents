"""LLM Provider 业务服务：

- encrypt/decrypt API key
- 按 provider_type 真实调用提供商 API 拉取模型列表（`sync_provider_models`）
- 支持通过 `MODEL_FETCHERS` 注入 mock（测试用）
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt, encrypt
from app.models.provider import LLMModel, LLMProvider
from app.schemas.provider import ModelBase, ProviderCreate, ProviderUpdate

logger = logging.getLogger(__name__)

# 连接提供商 API 的超时（秒）
_HTTP_TIMEOUT = 15.0


# ────────────── 模型拉取器（按 provider_type 分派） ──────────────
ModelFetcher = Callable[..., Awaitable[list[dict]]]


def _infer_model_type(model_id: str) -> str:
    """按 model_id 名称推断类型（API 未明确标注类型时的 fallback）。

    返回值（与 DB `model_type` 字段对齐）：
    - `embedding`：向量嵌入 / rerank
    - `image`：图像生成 / 编辑（DALL-E / Imagen / Flux / Seedream / Qwen-Image /
      Wan*-image / Kling image / Hunyuan-image / nano-banana 等）
    - `video`：视频生成（Seedance / Kling video / Wan*-t2v / Vidu / Hailuo /
      Hunyuan-video / CogVideo 等）
    - `completion`：旧式补全（davinci / curie）
    - `chat`：默认兜底（含 multimodal vision-capable chat 模型，如 qwen-vl-* /
      gpt-4o / claude-opus，因为它们 main output 是 text）

    判定顺序：embedding → video → image → completion → chat。video 优先于 image，
    因为像 `gemini-2.0-flash-preview-image-generation` 这种名字两个关键字都中，
    实际 output 是 image，所以先排掉 video 的强特征再走 image。
    """
    name = model_id.lower()

    if "embed" in name or "rerank" in name:
        return "embedding"

    # video：强特征词 + 已知厂商命名前缀
    video_markers = (
        "video", "seedance", "vidu", "hailuo", "cogvideo", "kling-v3-video",
        "kling-video", "klingvideo", "minimax-video", "wan2-t2v", "wan-t2v",
    )
    # 特殊：wanX.Y-t2v / wanX.Y-i2v 也是 video
    if any(m in name for m in video_markers):
        return "video"
    if "-t2v" in name or "-i2v" in name:
        return "video"

    # image：含 image / 已知 image 厂商关键字
    image_markers = (
        "image", "dall-e", "dall_e", "imagen", "flux", "seedream",
        "nano-banana", "banana-image", "cogview", "z-image", "wanx",
        "midjourney",
    )
    if any(m in name for m in image_markers):
        return "image"
    # wan2.X-image / wan-image
    if "-t2i" in name or "-i2i" in name:
        return "image"

    if name.endswith("-davinci-002") or name.endswith("-curie-001"):
        return "completion"
    return "chat"


async def _fetch_openai_compatible(
    *, api_key: str, base_url: str | None, default_base: str
) -> list[dict]:
    """OpenAI 兼容 `GET /models`（OpenAI / DeepSeek / 自建代理）。"""
    base = (base_url or default_base).rstrip("/")
    if not base:
        raise ValueError("缺少 base_url；custom provider 无法自动拉取模型，请手动添加")
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(f"{base}/models", headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
        payload = resp.json()
    items = payload.get("data") or payload.get("models") or []
    result: list[dict] = []
    for m in items:
        mid = m.get("id") or m.get("model") or m.get("name")
        if not mid:
            continue
        result.append(
            {
                "model_id": mid,
                "display_name": m.get("name") or m.get("display_name") or mid,
                "model_type": _infer_model_type(mid),
            }
        )
    return result


async def _fetch_gemini(*, api_key: str, base_url: str | None) -> list[dict]:
    """Google Generative Language API `GET /models?key=API_KEY`。"""
    base = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(f"{base}/models", params={"key": api_key})
        resp.raise_for_status()
        payload = resp.json()
    items = payload.get("models") or []
    result: list[dict] = []
    for m in items:
        full_name: str = m.get("name", "")
        if not full_name:
            continue
        mid = full_name.removeprefix("models/")
        methods = set(m.get("supportedGenerationMethods") or [])
        if "generateContent" in methods:
            mtype = "chat"
        elif "embedContent" in methods or "embedText" in methods:
            mtype = "embedding"
        else:
            # 跳过 countTokens 等辅助模型
            continue
        result.append(
            {
                "model_id": mid,
                "display_name": m.get("displayName") or mid,
                "model_type": mtype,
                "context_window": int(m.get("inputTokenLimit") or 0),
                "supports_vision": "generateContent" in methods,
                "supports_function_calling": "generateContent" in methods,
            }
        )
    return result


async def _fetch_anthropic(*, api_key: str, base_url: str | None) -> list[dict]:
    """Anthropic `GET /v1/models`（2024-06+ 版本可用）。"""
    base = (base_url or "https://api.anthropic.com").rstrip("/")
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(
            f"{base}/v1/models",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )
        resp.raise_for_status()
        payload = resp.json()
    items = payload.get("data") or []
    return [
        {
            "model_id": m["id"],
            "display_name": m.get("display_name") or m["id"],
            "model_type": "chat",
        }
        for m in items
        if "id" in m
    ]


async def _fetch_ollama(*, base_url: str | None, **_: object) -> list[dict]:
    """Ollama 本地 `GET /api/tags`。"""
    base = (base_url or "http://localhost:11434").rstrip("/")
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(f"{base}/api/tags")
        resp.raise_for_status()
        payload = resp.json()
    items = payload.get("models") or []
    return [
        {"model_id": m["name"], "display_name": m["name"], "model_type": "chat"}
        for m in items
        if "name" in m
    ]


async def _fetch_azure(*, api_key: str, base_url: str | None) -> list[dict]:
    """Azure OpenAI `GET /openai/models?api-version=...`，需要完整资源 endpoint。"""
    if not base_url:
        raise ValueError("Azure OpenAI 必须配置 base_url（资源 endpoint）")
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(
            f"{base}/openai/models",
            headers={"api-key": api_key},
            params={"api-version": "2024-02-01"},
        )
        resp.raise_for_status()
        payload = resp.json()
    items = payload.get("data") or []
    return [
        {
            "model_id": m["id"],
            "display_name": m["id"],
            "model_type": _infer_model_type(m["id"]),
        }
        for m in items
        if "id" in m
    ]


async def _fetch_custom(*, api_key: str, base_url: str | None) -> list[dict]:
    """自定义 provider：尝试按 OpenAI 兼容格式拉取。需用户填 base_url。
    若 base_url 末尾不含版本路径（如 /v1），自动补充 /v1 以匹配 OpenAI 兼容端点。
    """
    import re

    normalized: str | None = base_url
    if base_url:
        stripped = base_url.rstrip("/")
        if not re.search(r"/v\d+$", stripped):
            normalized = stripped + "/v1"
    return await _fetch_openai_compatible(api_key=api_key, base_url=normalized, default_base="")


# provider_type → fetcher 映射。测试可按需替换条目以注入 mock。
MODEL_FETCHERS: dict[str, ModelFetcher] = {
    "openai": lambda *, api_key, base_url: _fetch_openai_compatible(
        api_key=api_key, base_url=base_url, default_base="https://api.openai.com/v1"
    ),
    "deepseek": lambda *, api_key, base_url: _fetch_openai_compatible(
        api_key=api_key, base_url=base_url, default_base="https://api.deepseek.com/v1"
    ),
    "gemini": _fetch_gemini,
    "anthropic": _fetch_anthropic,
    "ollama": _fetch_ollama,
    "azure": _fetch_azure,
    "custom": _fetch_custom,
}


# ────────────── Provider CRUD ──────────────
async def list_providers(db: AsyncSession) -> Sequence[LLMProvider]:
    result = await db.execute(select(LLMProvider).order_by(LLMProvider.created_at))
    return result.scalars().all()


async def get_provider(db: AsyncSession, provider_id: uuid.UUID) -> LLMProvider | None:
    result = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    return result.scalar_one_or_none()


async def create_provider(db: AsyncSession, payload: ProviderCreate) -> LLMProvider:
    """创建 Provider 并**自动同步可用模型**。

    同步失败不回滚 Provider 创建，仅 log warning；
    用户可稍后在后台点"同步模型"按钮手动重试。
    """
    provider = LLMProvider(
        name=payload.name,
        provider_type=payload.provider_type,
        api_key=encrypt(payload.api_key),
        base_url=payload.base_url,
        extra_config=payload.extra_config,
        is_enabled=payload.is_enabled,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    # 尝试立即同步模型，失败不阻断创建
    try:
        await sync_provider_models(db, provider)
    except ProviderSyncError as exc:
        logger.warning(
            "Provider %s 创建成功但自动同步模型失败：%s（可在后台手动重试）",
            provider.name,
            exc,
        )

    return provider


async def update_provider(
    db: AsyncSession, provider: LLMProvider, payload: ProviderUpdate
) -> LLMProvider:
    """更新 Provider。若 api_key / base_url / provider_type 变化则重新同步模型。"""
    credential_changed = False
    if payload.name is not None:
        provider.name = payload.name
    if payload.provider_type is not None and payload.provider_type != provider.provider_type:
        provider.provider_type = payload.provider_type
        credential_changed = True
    if payload.api_key is not None and payload.api_key != "":
        provider.api_key = encrypt(payload.api_key)
        credential_changed = True
    if payload.base_url is not None and payload.base_url != provider.base_url:
        provider.base_url = payload.base_url
        credential_changed = True
    if payload.extra_config is not None:
        provider.extra_config = payload.extra_config
    if payload.is_enabled is not None:
        provider.is_enabled = payload.is_enabled
    await db.commit()
    await db.refresh(provider)

    if credential_changed:
        try:
            await sync_provider_models(db, provider)
        except ProviderSyncError as exc:
            logger.warning(
                "Provider %s 凭据变更后自动同步模型失败：%s（可在后台手动重试）",
                provider.name,
                exc,
            )
    return provider


async def delete_provider(db: AsyncSession, provider: LLMProvider) -> None:
    await db.delete(provider)
    await db.commit()


# ────────────── LLMModel ──────────────
async def list_models(db: AsyncSession, provider_id: uuid.UUID) -> Sequence[LLMModel]:
    result = await db.execute(
        select(LLMModel)
        .where(LLMModel.provider_id == provider_id)
        .order_by(LLMModel.model_type, LLMModel.model_id)
    )
    return result.scalars().all()


async def upsert_models(
    db: AsyncSession,
    provider: LLMProvider,
    model_specs: list[dict],
) -> list[LLMModel]:
    """按 (provider_id, model_id) upsert。保留用户手动设置的 is_enabled。"""
    existing = {m.model_id: m for m in await list_models(db, provider.id)}
    processed: list[LLMModel] = []
    for spec in model_specs:
        base = ModelBase(
            **{
                "model_type": "chat",
                "context_window": 0,
                "supports_vision": False,
                "supports_function_calling": False,
                "is_enabled": True,
                **spec,
            }
        )
        # 兜底分类：fetcher 给出 'chat' / 'completion' 时再跑一次 model_id 推断 ——
        # anthropic / ollama 等 fetcher 不区分 image/video/embedding，统一返回 'chat'，
        # 但模型名（如 imagen / hunyuan-video / seedream）已经能精准分类。
        # _infer_model_type 检出 image / video / embedding 则覆盖 fetcher 的默认值；
        # 否则保留 fetcher 提供的（可能更准的）值。
        if base.model_type in ("chat", "completion"):
            inferred = _infer_model_type(base.model_id)
            if inferred in ("image", "video", "embedding"):
                base.model_type = inferred
        if base.model_id in existing:
            m = existing[base.model_id]
            m.display_name = base.display_name
            m.model_type = base.model_type
            m.context_window = base.context_window or m.context_window
            m.supports_vision = base.supports_vision or m.supports_vision
            m.supports_function_calling = (
                base.supports_function_calling or m.supports_function_calling
            )
            # 不覆盖 is_enabled（用户手动禁用的模型，刷新不应重新启用）
        else:
            m = LLMModel(provider_id=provider.id, **base.model_dump())
            db.add(m)
        processed.append(m)
    await db.commit()
    for m in processed:
        await db.refresh(m)
    return processed


async def add_model(db: AsyncSession, provider: LLMProvider, spec: ModelBase) -> LLMModel:
    """手动添加一个模型（用于 custom provider 或拉取失败时的补救路径）。"""
    existing = await db.execute(
        select(LLMModel).where(
            LLMModel.provider_id == provider.id,
            LLMModel.model_id == spec.model_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"模型 {spec.model_id} 已存在")
    m = LLMModel(provider_id=provider.id, **spec.model_dump())
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


class ProviderSyncError(RuntimeError):
    """模型同步失败（网络 / 鉴权 / 响应格式错误）。"""


async def sync_provider_models(db: AsyncSession, provider: LLMProvider) -> list[LLMModel]:
    """调用提供商真实 API 拉取当前可用模型并 upsert 到 DB。"""
    fetcher = MODEL_FETCHERS.get(provider.provider_type)
    if not fetcher:
        raise ProviderSyncError(f"provider_type={provider.provider_type} 未配置拉取器")
    api_key = decrypt(provider.api_key)
    try:
        specs = await fetcher(api_key=api_key, base_url=provider.base_url)
    except httpx.HTTPStatusError as exc:
        raise ProviderSyncError(
            f"提供商返回 {exc.response.status_code}：{exc.response.text[:500]}"
        ) from exc
    except httpx.RequestError as exc:
        raise ProviderSyncError(f"连接提供商失败：{exc}") from exc
    except ValueError as exc:
        raise ProviderSyncError(str(exc)) from exc

    if not specs:
        logger.warning("⚠️ %s 返回空模型列表", provider.name)
        return []
    models = await upsert_models(db, provider, specs)
    logger.info("✅ 已同步 %d 个模型 (provider=%s)", len(models), provider.name)
    return models


async def update_model(
    db: AsyncSession,
    model: LLMModel,
    updates: dict,
) -> LLMModel:
    for k, v in updates.items():
        if v is not None:
            setattr(model, k, v)
    await db.commit()
    await db.refresh(model)
    return model


def reveal_api_key(provider: LLMProvider) -> str:
    """返回明文 API Key（仅内部构建 LLM 客户端时调用，禁止返回给前端）。"""
    return decrypt(provider.api_key)
