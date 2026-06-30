"""辅助模型工具：`invoke_aux_model`

允许主 LLM 按 alias / role 调用 Agent 已绑定的辅助模型（如 image-generation 的
nano-banana、embedding、rerank 等），并把结果返回。

参数：
- alias_or_role(str)：优先按 alias 精确匹配，退化到按 role 匹配第一条
- input(str)：输入文本（图片生成为 prompt；embedding 为待嵌入文本；vision/chat 为消息）
- mode(str, 可选)：对 chat 模型默认 "chat"；image 默认 "image"；embedding 默认 "embedding"。显式传值可覆盖
- config_overrides(dict, 可选)：透传给 LiteLLM 的额外参数（size、n、response_format 等）
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import uuid as _uuid
from typing import Any

import httpx
from langchain_core.tools import StructuredTool

from app.core.config import settings
from app.core.encryption import decrypt
from app.services.storage_service import get_storage
from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


async def _resolve_binding(ctx: BuiltinToolContext, alias_or_role: str):
    """从 DB 加载 Agent 的 aux model 绑定；优先 alias，再按 role。"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.agent import Agent, AgentAuxModel
    from app.models.provider import LLMProvider

    if ctx.db_factory is None or "agent_id" not in (ctx.extra or {}):
        return None, "❌ 工具上下文缺失 agent_id，无法定位辅助模型"
    agent_id = ctx.extra["agent_id"]

    async with ctx.db_factory() as db:
        result = await db.execute(
            select(Agent)
            .options(selectinload(Agent.aux_models).joinedload(AgentAuxModel.model))
            .where(Agent.id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return None, "❌ Agent 未找到"
        candidates = list(agent.aux_models)
        binding = None
        # 1) alias 精确匹配
        for b in candidates:
            if b.alias and b.alias == alias_or_role:
                binding = b
                break
        # 2) role 匹配
        if not binding:
            for b in candidates:
                if b.role == alias_or_role:
                    binding = b
                    break
        if not binding:
            avail = (
                ", ".join(f"{b.alias or '-'}[{b.role}]" for b in candidates) or "（未绑定辅助模型）"
            )
            return None, f"❌ 未找到辅助模型 {alias_or_role!r}。已绑定：{avail}"

        provider = await db.get(LLMProvider, binding.model.provider_id)
        if not provider:
            return None, "❌ 辅助模型对应的 Provider 不存在"
        api_key = decrypt(provider.api_key)

        return {
            "alias": binding.alias,
            "role": binding.role,
            "provider_type": provider.provider_type,
            "base_url": provider.base_url,
            "api_key": api_key,
            "model_id": binding.model.model_id,
            "model_type": binding.model.model_type,
            "config": binding.config or {},
        }, None


_IMAGE_RETRY_DELAY_SEC = 8.0  # 留够 Cloudflare 免费版 burst window 清掉的时间


# ─────────────── 第三方资源镜像到 S3 ───────────────

# 第三方生成服务返回的 URL（nebula / aliyun DashScope / volcengine TOS / OpenAI Azure Blob 等）
# 都是**临时签名 URL**，通常 24h-7d 过期。我们把它们镜像到自己 S3，返回稳定签名链接。
# 路径前缀：aux-image/ / aux-video/，与 b64 上传保持一致。
_DOWNLOAD_TIMEOUT_SEC = 180.0  # 30MB video segment + 慢链路 3min 足够
_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # 200MB 上限，防御 LLM 拿到伪 URL 拖大流


_CONTENT_TYPE_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}


def _ext_from_url_path(url: str, fallback: str) -> str:
    """从 URL path 提取扩展名（取查询串前的最后一个 . 后缀，限制白名单）。"""
    from urllib.parse import urlparse
    try:
        path = urlparse(url).path.lower()
    except Exception:
        return fallback
    if "." not in path:
        return fallback
    ext = path.rsplit(".", 1)[-1]
    if 1 <= len(ext) <= 4 and ext.isalnum():
        return ext
    return fallback


async def _mirror_third_party_url_to_s3(
    url: str,
    *,
    kind: str,  # "image" | "video"
) -> str:
    """下载第三方临时 URL → 上传到我们 S3 → 返回长期签名 URL。

    失败时回退到原 URL，不阻塞 worker。
    """
    if not url or not url.startswith(("http://", "https://")):
        return url
    # 已经是我们自己的 S3 / CDN 域名 → 不再二次镜像
    public_host = getattr(settings, "S3_PUBLIC_URL_HOST", "") or ""
    if public_host and public_host in url:
        return url
    try:
        async with httpx.AsyncClient(
            timeout=_DOWNLOAD_TIMEOUT_SEC, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            if resp.status_code >= 300:
                logger.warning(
                    "mirror_third_party: 下载失败 HTTP %d url=%s",
                    resp.status_code, url[:120],
                )
                return url
            blob = resp.content
            if not blob or len(blob) == 0:
                return url
            if len(blob) > _MAX_DOWNLOAD_BYTES:
                logger.warning(
                    "mirror_third_party: blob 超过 %dMB 上限，跳过镜像 url=%s",
                    _MAX_DOWNLOAD_BYTES // 1024 // 1024, url[:120],
                )
                return url
            content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not content_type:
            content_type = "video/mp4" if kind == "video" else "image/png"
        default_ext = "mp4" if kind == "video" else "png"
        ext = _CONTENT_TYPE_EXT.get(content_type) or _ext_from_url_path(url, default_ext)
        key = (
            f"aux-{kind}/{hashlib.sha1(blob).hexdigest()[:16]}-{_uuid.uuid4().hex[:6]}.{ext}"
        )
        await get_storage().upload(key, blob, content_type=content_type)
        signed = await get_storage().presigned_url(
            key, expires_in=settings.S3_ARTIFACT_URL_EXPIRE,
        )
        logger.info(
            "🪞 mirror_third_party: %s %dB → s3:%s",
            kind, len(blob), key,
        )
        return signed
    except Exception as exc:
        logger.warning("mirror_third_party 上传 S3 失败（回退原 URL）：%s", exc)
        return url


async def _do_image(
    *,
    litellm,
    route: str,
    api_key: str,
    api_base: str | None,
    input_text: str,
    merged_config: dict[str, Any],
) -> str:
    """单次 image 调用 + base64 解码 + S3 上传，返回成功或失败文案。"""
    resp = await litellm.aimage_generation(
        model=route,
        prompt=input_text,
        api_key=api_key,
        api_base=api_base,
        **merged_config,
    )
    data = resp.get("data") if isinstance(resp, dict) else getattr(resp, "data", None)
    if not data:
        return f"⚠️ 图像生成无结果：{resp}"
    first = data[0]
    url = first.get("url") if isinstance(first, dict) else getattr(first, "url", None)
    b64 = first.get("b64_json") if isinstance(first, dict) else getattr(first, "b64_json", None)
    if url:
        mirrored = await _mirror_third_party_url_to_s3(url, kind="image")
        return f"✅ 图像生成成功：{mirrored}"
    if b64:
        img_bytes = base64.b64decode(b64)
        key = (
            f"aux-image/{hashlib.sha1(img_bytes).hexdigest()[:16]}-{_uuid.uuid4().hex[:6]}.png"
        )
        try:
            await get_storage().upload(key, img_bytes, content_type="image/png")
            signed = await get_storage().presigned_url(
                key, expires_in=settings.S3_ARTIFACT_URL_EXPIRE
            )
            return f"✅ 图像生成成功（已上传 S3）：{signed}"
        except Exception as exc:
            logger.exception("aux image 上传 S3 失败")
            return f"✅ 图像已生成（{len(img_bytes)} bytes）但未上传 S3：{exc}"
    return f"⚠️ 图像响应无 url/b64_json 字段：{first}"


def _is_transient_litellm_error(exc: BaseException) -> bool:
    """瞬态判定：Cloudflare 代理限流 / 上游 5xx / 连接抖动 → 值得 sleep 后重试一次。"""
    msg = str(exc).lower()
    # 优先排除"永久错误"——内容审核 / 隐私 / prompt 不合规 / 维度不匹配等
    # 改输入才能修复，重试同输入只是浪费配额 + 让 LLM 撞 max_iterations
    if _is_non_retriable_error(exc):
        return False
    if any(s in msg for s in (
        "connection reset", "connection aborted", "broken pipe",
        "[errno 104]", "timed out", "internalservererror",
        "503", "502", "504", "rate limit", "ratelimit",
    )):
        return True
    name = exc.__class__.__name__.lower()
    return "internalservererror" in name or "ratelimit" in name or "timeout" in name


# 永久错误关键词（重试同输入只会同样失败）——按 vendor 报错字面量整理
_NON_RETRIABLE_KEYWORDS: tuple[str, ...] = (
    # 内容审核 / 安全 / 隐私
    "sensitive content", "sensitivecontent", "inappropriate content",
    "privacyinformation", "privacy information",
    "data_inspection_failed", "datainspectionfailed",
    "content policy", "contentpolicy",
    "audit_failed", "auditfailed", "moderation",
    "real person", "real_person",
    # 输入参数 / schema 类
    "invalidparameter", "invalid parameter", "invalid_parameter",
    "duration is not valid", "size is not valid",
    "image size must be at least",
    # 鉴权
    "invalid_api_key", "invalid api key", "unauthorized",
    "permissiondenied", "permission denied",
    # 模型不存在 / 不可访问
    "model_not_found", "model not found", "modelnotfound",
    "endpoint or model", "does not exist or you do not have access",
)


def _is_non_retriable_error(exc: BaseException) -> bool:
    """判断错误是否"永久不可重试"——重试同输入也会同样失败的语义错。"""
    msg = str(exc).lower()
    return any(k in msg for k in _NON_RETRIABLE_KEYWORDS)


def _classify_error_brief(exc_str: str) -> str | None:
    """从错误字符串里提取"为什么不能重试"的中文短摘要，供 LLM 看懂。返回 None 表示不是已知永久错误。"""
    s = exc_str.lower()
    if "sensitive content" in s or "sensitivecontent" in s or "privacyinformation" in s:
        return "内容审核拒收（图片含真人 / 隐私 / 敏感内容）—— 必须换图或改 prompt，**绝不要重试同一输入**"
    if "data_inspection_failed" in s or "moderation" in s or "content policy" in s:
        return "上游内容审核拒收 —— 必须换 prompt 或换图，重试无效"
    if "duration is not valid" in s or ("duration" in s and "not valid" in s):
        return "duration 取值不在模型白名单（5/10 秒）—— 改成合法值，**严禁** 用同值重试"
    if "size" in s and ("not valid" in s or "must be at least" in s):
        return "size 不符合模型最小像素要求 —— 改 size，重试同值无效"
    if "invalid_api_key" in s or "unauthorized" in s:
        return "API key 失效 / 鉴权失败 —— 管理员介入，agent 重试无效"
    if "model_not_found" in s or "endpoint or model" in s:
        return "模型不存在 / 无权限 —— 换 model_spec 或联系管理员"
    if "invalidparameter" in s or "invalid_parameter" in s:
        return "参数非法 —— 检查并改正参数，重试无效"
    return None


# ════════════════════════════════════════════════════════════════════════
# 阿里云 DashScope + 火山引擎方舟 + Nebula 适配
# ════════════════════════════════════════════════════════════════════════


def _is_dashscope(base_url: str | None) -> bool:
    return bool(base_url and "dashscope.aliyuncs.com" in base_url)


def _dashscope_native_root(base_url: str | None) -> str:
    """把 provider 配的 `/compatible-mode/v1` 还原成 native `/api/v1` 根。"""
    if not base_url:
        return "https://dashscope.aliyuncs.com/api/v1"
    base = base_url.rstrip("/")
    for suffix in ("/compatible-mode/v1", "/v1", "/api/v1"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return f"{base.rstrip('/')}/api/v1"


def _is_nebula(base_url: str | None) -> bool:
    return bool(base_url and "ai-nebula.com" in base_url)


def _is_volcengine(base_url: str | None) -> bool:
    """火山引擎方舟 ark API：base_url 形如 https://ark.cn-beijing.volces.com/api/v3"""
    return bool(base_url and ("volces.com" in base_url or "ark." in base_url))


_DASHSCOPE_TASK_POLL_INTERVAL_SEC = 3.0
_DASHSCOPE_TASK_MAX_WAIT_SEC = 240.0  # image 一般 ~30s；video 60-180s
_NEBULA_VIDEO_POLL_INTERVAL_SEC = 6.0
_NEBULA_VIDEO_MAX_WAIT_SEC = 360.0
_VOLCENGINE_VIDEO_POLL_INTERVAL_SEC = 6.0
_VOLCENGINE_VIDEO_MAX_WAIT_SEC = 480.0

_NEBULA_I2V_IMAGE_ALIASES = ("image", "image_url", "img_url", "first_frame_url", "first_frame_image")

# 各家 video 模型对 duration 参数的有效取值约束
_VIDEO_DURATION_WHITELIST: dict[str, tuple[int, ...]] = {
    "doubao-seedance-2-0-fast-260128": (5, 10),
    "doubao-seedance-2-0-260128": (5, 10),
    "doubao-seedance-1-5-pro-251215": (5, 10),
    "doubao-seedance-1-5-pro-251215-noAudio": (5, 10),
    "doubao-seedance-1-0-pro-250528": (5, 10),
    "doubao-seedance-1-0-lite-t2v-250428": (5, 10),
    "doubao-seedance-1-0-lite-i2v-250428": (5, 10),
    "wan2.5-t2v-preview": (5, 10),
    "wan2.5-i2v-preview": (5, 10),
    "wan2.6-t2v": (5, 10),
    "wan2.6-i2v": (5, 10),
    "wan2.6-i2v-flash": (5, 10),
    "MiniMax-Hailuo-02": (6,),
    "MiniMax-Hailuo-2.3": (6,),
    "MiniMax-Hailuo-2.3-Fast": (6,),
}


def _validate_video_duration(model_id: str, requested: int | float | None) -> int | None:
    """按 whitelist 校验 duration；不合法直接抛错给出友好提示。"""
    if requested is None:
        return None
    try:
        d = int(requested)
    except (TypeError, ValueError):
        return requested
    allowed = _VIDEO_DURATION_WHITELIST.get(model_id)
    if allowed is None:
        return d
    if d not in allowed:
        raise RuntimeError(
            f"❌ duration={d}s 不被 {model_id} 支持。该模型仅接受 duration ∈ {list(allowed)}。"
            f"请改成 {list(allowed)} 之一重试；若用户要更长视频，请生成多个片段后再拼接，"
            f"**不要用相同 duration 反复重试**。"
        )
    return d


async def _emit_aux_progress(
    ctx: BuiltinToolContext | None,
    *,
    task_id: str,
    mode: str,  # "image" | "video"
    provider: str,  # "aliyun" | "nebula" | "volcengine"
    status: str,
    elapsed_sec: float,
    estimated_total_sec: float,
    label: str | None = None,
) -> None:
    """向 SSE 流推送 data-aux-task-progress 事件（前端显示生成进度卡片）。"""
    if ctx is None:
        return
    progress_pct = min(100, int(elapsed_sec / max(estimated_total_sec, 1.0) * 100))
    await ctx.emit({
        "type": "data-aux-task-progress",
        "data": {
            "task_id": task_id,
            "mode": mode,
            "provider": provider,
            "status": status,
            "elapsed_sec": round(elapsed_sec, 1),
            "estimated_total_sec": estimated_total_sec,
            "progress_pct": progress_pct,
            "label": label,
        },
    })


async def _dashscope_submit_and_poll(
    *,
    api_key: str,
    submit_url: str,
    body: dict[str, Any],
    kind: str,
    ctx: BuiltinToolContext | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """提交 DashScope 异步任务 → 轮询 → 返回最终 `output` dict。失败抛 RuntimeError。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(submit_url, json=body, headers=headers)
        if resp.status_code >= 300:
            raise RuntimeError(
                f"DashScope {kind} 任务提交失败 HTTP {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()
        task_id = (data.get("output") or {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"DashScope {kind} 响应缺 task_id：{data}")

    native_root = submit_url.split("/services/", 1)[0]
    task_url = f"{native_root}/tasks/{task_id}"
    poll_headers = {"Authorization": f"Bearer {api_key}"}

    start_t = asyncio.get_event_loop().time()
    deadline = start_t + _DASHSCOPE_TASK_MAX_WAIT_SEC
    estimated = 30.0 if kind == "image" else 120.0
    last_status = "PENDING"
    await _emit_aux_progress(
        ctx, task_id=task_id, mode=kind, provider="aliyun",
        status="submitted", elapsed_sec=0.0, estimated_total_sec=estimated, label=label,
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            await asyncio.sleep(_DASHSCOPE_TASK_POLL_INTERVAL_SEC)
            r = await client.get(task_url, headers=poll_headers)
            if r.status_code >= 300:
                raise RuntimeError(
                    f"DashScope {kind} 轮询失败 HTTP {r.status_code}: {r.text[:300]}"
                )
            payload = r.json()
            output = payload.get("output") or {}
            status = output.get("task_status") or "UNKNOWN"
            last_status = status
            elapsed = asyncio.get_event_loop().time() - start_t
            await _emit_aux_progress(
                ctx, task_id=task_id, mode=kind, provider="aliyun",
                status=str(status).lower(), elapsed_sec=elapsed,
                estimated_total_sec=estimated, label=label,
            )
            if status == "SUCCEEDED":
                return output
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                err_msg = output.get("message") or payload.get("message") or "(no msg)"
                raise RuntimeError(f"DashScope {kind} 任务 {status}：{err_msg}")
            if asyncio.get_event_loop().time() >= deadline:
                raise RuntimeError(
                    f"DashScope {kind} 轮询超时（>{_DASHSCOPE_TASK_MAX_WAIT_SEC:.0f}s）"
                    f"最后状态 {last_status} task_id={task_id}"
                )


def _is_legacy_wanx_image(model_id: str) -> bool:
    name = model_id.lower()
    return name.startswith("wanx-") or name == "wanx-v1"


async def _do_aliyun_image(
    *,
    api_key: str,
    base_url: str | None,
    model_id: str,
    prompt: str,
    merged_config: dict[str, Any],
    ctx: BuiltinToolContext | None = None,
    label: str | None = None,
) -> str:
    """阿里 DashScope image 生成。现代模型走同步 multimodal-generation；wanx 走异步 t2i。"""
    native_root = _dashscope_native_root(base_url)
    if _is_legacy_wanx_image(model_id):
        submit_url = f"{native_root}/services/aigc/text2image/image-synthesis"
        body: dict[str, Any] = {
            "model": model_id,
            "input": {"prompt": prompt},
            "parameters": dict(merged_config) if merged_config else {},
        }
        output = await _dashscope_submit_and_poll(
            api_key=api_key, submit_url=submit_url, body=body, kind="image",
            ctx=ctx, label=label,
        )
        results = output.get("results") or []
        urls = [r["url"] for r in results if isinstance(r, dict) and r.get("url")]
    else:
        submit_url = f"{native_root}/services/aigc/multimodal-generation/generation"
        body = {
            "model": model_id,
            "input": {
                "messages": [
                    {"role": "user", "content": [{"text": prompt}]},
                ],
            },
            "parameters": dict(merged_config) if merged_config else {},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(submit_url, json=body, headers=headers)
        if resp.status_code >= 300:
            raise RuntimeError(
                f"DashScope image 生成失败 HTTP {resp.status_code}: {resp.text[:400]}"
            )
        data = resp.json()
        urls = []
        for choice in (data.get("output") or {}).get("choices") or []:
            msg = choice.get("message") or {}
            for part in msg.get("content") or []:
                if isinstance(part, dict) and part.get("image"):
                    urls.append(part["image"])
    if not urls:
        return "⚠️ 阿里 image 任务成功但无 URL 输出"
    mirrored = await asyncio.gather(
        *[_mirror_third_party_url_to_s3(u, kind="image") for u in urls]
    )
    if len(mirrored) == 1:
        return f"✅ 图像生成成功：{mirrored[0]}"
    return f"✅ 图像生成成功（{len(mirrored)} 张）：\n" + "\n".join(mirrored)


async def _do_aliyun_video(
    *,
    api_key: str,
    base_url: str | None,
    model_id: str,
    prompt: str,
    merged_config: dict[str, Any],
    ctx: BuiltinToolContext | None = None,
    label: str | None = None,
) -> str:
    """走 DashScope `/video-generation/video-synthesis` 异步接口。"""
    native_root = _dashscope_native_root(base_url)
    submit_url = f"{native_root}/services/aigc/video-generation/video-synthesis"
    # 别名归一：image_url / image → img_url（DashScope 原生字段名）
    if "image_url" in merged_config and "img_url" not in merged_config:
        merged_config["img_url"] = merged_config.pop("image_url")
    if "image" in merged_config and "img_url" not in merged_config:
        merged_config["img_url"] = merged_config.pop("image")
    user_input_extra = {
        k: merged_config.pop(k)
        for k in list(merged_config.keys())
        if k in ("img_url", "first_frame_url", "last_frame_url", "ref_images_url")
    }
    body: dict[str, Any] = {
        "model": model_id,
        "input": {"prompt": prompt, **user_input_extra},
        "parameters": dict(merged_config) if merged_config else {},
    }
    output = await _dashscope_submit_and_poll(
        api_key=api_key, submit_url=submit_url, body=body, kind="video",
        ctx=ctx, label=label,
    )
    video_url = output.get("video_url")
    if video_url:
        mirrored = await _mirror_third_party_url_to_s3(video_url, kind="video")
        return f"✅ 视频生成成功：{mirrored}"
    results = output.get("results") or []
    urls = [r["url"] for r in results if isinstance(r, dict) and r.get("url")]
    if urls:
        mirrored_list = await asyncio.gather(
            *[_mirror_third_party_url_to_s3(u, kind="video") for u in urls]
        )
        return "✅ 视频生成成功：\n" + "\n".join(mirrored_list)
    return f"⚠️ 阿里 video 任务成功但无 URL：{output}"


async def _do_nebula_image(
    *,
    api_key: str,
    base_url: str | None,
    model_id: str,
    prompt: str,
    merged_config: dict[str, Any],
) -> str:
    """Nebula `/v1/images/generations` 同步接口（绕开 litellm 的 model_dump bug）。"""
    base = (base_url or "https://llm.ai-nebula.com").rstrip("/")
    url = f"{base}/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {"model": model_id, "prompt": prompt, "n": 1}
    body.update(merged_config)

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=body, headers=headers)
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Nebula image 请求失败 HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            payload = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"Nebula image 响应非 JSON：{resp.text[:300]}（{exc}）"
            ) from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not data and isinstance(payload, dict) and payload.get("url"):
        data = [{"url": payload["url"]}]
    if not data:
        return f"⚠️ Nebula image 响应无 data 字段：{str(payload)[:300]}"
    first = data[0] if isinstance(data, list) and data else {}
    img_url = first.get("url") if isinstance(first, dict) else None
    b64 = first.get("b64_json") if isinstance(first, dict) else None
    if img_url:
        mirrored = await _mirror_third_party_url_to_s3(img_url, kind="image")
        return f"✅ 图像生成成功：{mirrored}"
    if b64:
        img_bytes = base64.b64decode(b64)
        key = f"aux-image/{hashlib.sha1(img_bytes).hexdigest()[:16]}-{_uuid.uuid4().hex[:6]}.png"
        try:
            await get_storage().upload(key, img_bytes, content_type="image/png")
            signed = await get_storage().presigned_url(
                key, expires_in=settings.S3_ARTIFACT_URL_EXPIRE
            )
            return f"✅ 图像生成成功（已上传 S3）：{signed}"
        except Exception as exc:
            logger.exception("Nebula image S3 上传失败")
            return f"✅ 图像已生成（{len(img_bytes)} bytes）但未上传 S3：{exc}"
    return f"⚠️ Nebula image 响应无 url/b64_json：{str(first)[:300]}"


# Seedream（doubao-seedream-*）文生图：Ark 要求像素 >= 此最小值，否则 HTTP 400
# 「image size must be at least 3686400 pixels」。缺省/过小都会首调失败、白白浪费一次调用。
_SEEDREAM_MIN_PIXELS = 3_686_400  # ≈ 1920x1920
_SEEDREAM_DEFAULT_SIZE = "2048x2048"  # 4194304 px，安全 > 最小值，e2e 实测可用


def _parse_size_pixels(size: Any) -> int | None:
    """把 'WxH' / 'W*H' 解析成像素数；具名尺寸（'2K'）/ 非法值返回 None。"""
    if not isinstance(size, str):
        return None
    import re
    m = re.match(r"^\s*(\d+)\s*[x*X×]\s*(\d+)\s*$", size)
    if not m:
        return None
    return int(m.group(1)) * int(m.group(2))


def _ensure_image_size(model_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """Seedream 系列：size 缺省或可解析且过小 → 补/升到安全默认；已合规或具名 size 不动。

    只对 doubao-seedream-*（文生图）生效；seededit（图生图）/ 其它模型接口要求不同，不干预。
    """
    if "seedream" not in (model_id or "").lower():
        return config
    out = dict(config)
    size = out.get("size")
    if size is None or size == "":
        out["size"] = _SEEDREAM_DEFAULT_SIZE
        return out
    px = _parse_size_pixels(size)
    if px is not None and px < _SEEDREAM_MIN_PIXELS:
        out["size"] = _SEEDREAM_DEFAULT_SIZE
    return out


async def _do_volcengine_image(
    *,
    api_key: str,
    base_url: str | None,
    model_id: str,
    prompt: str,
    merged_config: dict[str, Any],
) -> str:
    """火山方舟 `/api/v3/images/generations` 同步接口（Seedream / SeedEdit）。"""
    base = (base_url or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    url = f"{base}/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    normalized = _ensure_image_size(model_id, dict(merged_config))
    for alias in ("image_url", "img_url", "first_frame_url"):
        if alias in normalized and "image" not in normalized:
            normalized["image"] = normalized.pop(alias)
    body: dict[str, Any] = {"model": model_id, "prompt": prompt}
    body.update(normalized)

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=body, headers=headers)
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Volcengine image 请求失败 HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            payload = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"Volcengine image 响应非 JSON：{resp.text[:300]}（{exc}）"
            ) from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not data:
        return f"⚠️ Volcengine image 响应无 data 字段：{str(payload)[:300]}"
    first = data[0] if isinstance(data, list) and data else {}
    img_url = first.get("url") if isinstance(first, dict) else None
    b64 = first.get("b64_json") if isinstance(first, dict) else None
    if img_url:
        mirrored = await _mirror_third_party_url_to_s3(img_url, kind="image")
        return f"✅ 图像生成成功：{mirrored}"
    if b64:
        img_bytes = base64.b64decode(b64)
        key = f"aux-image/{hashlib.sha1(img_bytes).hexdigest()[:16]}-{_uuid.uuid4().hex[:6]}.png"
        try:
            await get_storage().upload(key, img_bytes, content_type="image/png")
            signed = await get_storage().presigned_url(
                key, expires_in=settings.S3_ARTIFACT_URL_EXPIRE,
            )
            return f"✅ 图像生成成功（已上传 S3）：{signed}"
        except Exception as exc:
            logger.exception("Volcengine image S3 上传失败")
            return f"✅ 图像已生成（{len(img_bytes)} bytes）但未上传 S3：{exc}"
    return f"⚠️ Volcengine image 响应无 url/b64_json：{str(first)[:300]}"


async def _do_volcengine_video(
    *,
    api_key: str,
    base_url: str | None,
    model_id: str,
    prompt: str,
    merged_config: dict[str, Any],
    ctx: BuiltinToolContext | None = None,
    label: str | None = None,
) -> str:
    """火山方舟 `/api/v3/contents/generations/tasks` 异步接口（Seedance / Doubao video）。"""
    base = (base_url or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    submit_url = f"{base}/contents/generations/tasks"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    normalized = dict(merged_config)
    first_frame_url: str | None = None
    for alias in ("image", "image_url", "img_url", "first_frame_url", "first_frame_image"):
        v = normalized.pop(alias, None)
        if first_frame_url is None and isinstance(v, str) and v:
            first_frame_url = v

    if "duration" in normalized:
        validated = _validate_video_duration(model_id, normalized["duration"])
        if validated is not None:
            normalized["duration"] = validated

    content_parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if first_frame_url:
        content_parts.append({"type": "image_url", "image_url": {"url": first_frame_url}})

    body: dict[str, Any] = {"model": model_id, "content": content_parts}
    body.update(normalized)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(submit_url, json=body, headers=headers)
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Volcengine video 任务提交失败 HTTP {resp.status_code}: {resp.text[:300]}"
            )
        task_data = resp.json()
        task_id = task_data.get("id") or task_data.get("task_id")
        if not task_id:
            raise RuntimeError(f"Volcengine video 响应缺 id：{resp.text[:200]}")

    poll_url = f"{submit_url}/{task_id}"
    start_t = asyncio.get_event_loop().time()
    deadline = start_t + _VOLCENGINE_VIDEO_MAX_WAIT_SEC
    last_status = "submitted"
    estimated = 240.0

    await _emit_aux_progress(
        ctx, task_id=str(task_id), mode="video", provider="volcengine",
        status="submitted", elapsed_sec=0.0, estimated_total_sec=estimated, label=label,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            await asyncio.sleep(_VOLCENGINE_VIDEO_POLL_INTERVAL_SEC)
            r = await client.get(poll_url, headers=headers)
            elapsed = asyncio.get_event_loop().time() - start_t
            if r.status_code >= 300:
                last_status = f"poll {r.status_code}"
                await _emit_aux_progress(
                    ctx, task_id=str(task_id), mode="video", provider="volcengine",
                    status="polling_5xx", elapsed_sec=elapsed,
                    estimated_total_sec=estimated, label=label,
                )
                if asyncio.get_event_loop().time() >= deadline:
                    raise RuntimeError(
                        f"Volcengine video 轮询持续失败 HTTP {r.status_code} task={task_id}"
                    )
                continue
            data = r.json() if r.text else {}
            status = str(data.get("status") or "unknown").lower()
            last_status = status
            await _emit_aux_progress(
                ctx, task_id=str(task_id), mode="video", provider="volcengine",
                status=status, elapsed_sec=elapsed,
                estimated_total_sec=estimated, label=label,
            )
            if status in ("succeeded", "completed", "done"):
                content_obj = data.get("content") or data.get("result") or data.get("output") or {}
                if isinstance(content_obj, list):
                    content_obj = content_obj[0] if content_obj else {}
                video_url = (
                    (content_obj.get("video_url") if isinstance(content_obj, dict) else None)
                    or data.get("video_url")
                )
                if not video_url:
                    raise RuntimeError(
                        f"Volcengine video 任务 succeeded 但 video_url 字段为空：{str(data)[:300]}"
                    )
                mirrored = await _mirror_third_party_url_to_s3(video_url, kind="video")
                return f"✅ 视频生成成功：{mirrored}"
            if status in ("failed", "canceled", "cancelled"):
                err = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else None
                msg = err or data.get("message") or data.get("failure_reason") or "(no msg)"
                raise RuntimeError(f"Volcengine video 任务 {status}：{msg}")
            if asyncio.get_event_loop().time() >= deadline:
                raise RuntimeError(
                    f"Volcengine video 轮询超时（>{_VOLCENGINE_VIDEO_MAX_WAIT_SEC:.0f}s）"
                    f"最后状态 {last_status} task_id={task_id}"
                )


async def _do_nebula_video(
    *,
    api_key: str,
    base_url: str | None,
    model_id: str,
    prompt: str,
    merged_config: dict[str, Any],
    ctx: BuiltinToolContext | None = None,
    label: str | None = None,
) -> str:
    """Nebula `/v1/video/generations` 异步接口（含 Seedance / Hailuo / Wan-t2v）。"""
    base = (base_url or "https://llm.ai-nebula.com").rstrip("/")
    submit_url = f"{base}/v1/video/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    normalized = dict(merged_config)
    for alias in _NEBULA_I2V_IMAGE_ALIASES:
        if alias == "image":
            continue
        if alias in normalized:
            normalized.setdefault("image", normalized.pop(alias))
    if "duration" in normalized:
        validated = _validate_video_duration(model_id, normalized["duration"])
        if validated is not None:
            normalized["duration"] = validated
    body: dict[str, Any] = {"model": model_id, "prompt": prompt}
    body.update(normalized)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(submit_url, json=body, headers=headers)
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Nebula video 任务提交失败 HTTP {resp.status_code}: {resp.text[:300]}"
            )
        task_id = resp.json().get("task_id")
        if not task_id:
            raise RuntimeError(f"Nebula video 响应缺 task_id：{resp.text[:200]}")

    poll_url = f"{base}/v1/video/generations/{task_id}"
    start_t = asyncio.get_event_loop().time()
    deadline = start_t + _NEBULA_VIDEO_MAX_WAIT_SEC
    last_status = "submitted"
    estimated = 180.0
    await _emit_aux_progress(
        ctx, task_id=task_id, mode="video", provider="nebula",
        status="submitted", elapsed_sec=0.0, estimated_total_sec=estimated, label=label,
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            await asyncio.sleep(_NEBULA_VIDEO_POLL_INTERVAL_SEC)
            r = await client.get(poll_url, headers=headers)
            elapsed = asyncio.get_event_loop().time() - start_t
            if r.status_code >= 300:
                last_status = f"poll {r.status_code}"
                await _emit_aux_progress(
                    ctx, task_id=task_id, mode="video", provider="nebula",
                    status="polling_5xx", elapsed_sec=elapsed,
                    estimated_total_sec=estimated, label=label,
                )
                if asyncio.get_event_loop().time() >= deadline:
                    raise RuntimeError(
                        f"Nebula video 轮询持续失败 HTTP {r.status_code} task={task_id}"
                    )
                continue
            data = r.json() if r.text else {}
            status = data.get("status") or data.get("task_status") or "unknown"
            last_status = status
            await _emit_aux_progress(
                ctx, task_id=task_id, mode="video", provider="nebula",
                status=str(status).lower(), elapsed_sec=elapsed,
                estimated_total_sec=estimated, label=label,
            )
            if status in ("succeeded", "SUCCEEDED", "done", "completed"):
                url = data.get("url")
                if not url:
                    raise RuntimeError(
                        f"Nebula video 任务 succeeded 但 url 字段为空：{data}"
                    )
                mirrored = await _mirror_third_party_url_to_s3(url, kind="video")
                return f"✅ 视频生成成功：{mirrored}"
            if status in ("failed", "FAILED", "canceled"):
                msg = data.get("error") or data.get("message") or "(no msg)"
                raise RuntimeError(f"Nebula video 任务 {status}：{msg}")
            if asyncio.get_event_loop().time() >= deadline:
                raise RuntimeError(
                    f"Nebula video 轮询超时（>{_NEBULA_VIDEO_MAX_WAIT_SEC:.0f}s）"
                    f"最后状态 {last_status} task_id={task_id}"
                )


async def _invoke_litellm(
    *,
    provider_type: str,
    base_url: str | None,
    api_key: str,
    model_id: str,
    mode: str,
    input_text: str,
    merged_config: dict[str, Any],
    ctx: BuiltinToolContext | None = None,
    label: str | None = None,
) -> str:
    """统一入口。**仅 image 模式** 在瞬态错误时强制 sleep 一次再重试一次。

    image / video 路由按 base_url 自动检测 DashScope / Volcengine / Nebula 走原生 API。
    chat / embedding 走 LiteLLM。
    """
    import asyncio as _asyncio
    import litellm

    route = f"openai/{model_id}" if provider_type == "custom" else f"{provider_type}/{model_id}"
    api_base = base_url or None

    # ── 阿里 DashScope：image / video 走原生异步 API（LiteLLM openai-compat 不支持）──
    if _is_dashscope(base_url) and mode in ("image", "video"):
        async def _call_aliyun_once() -> str:
            if mode == "image":
                return await _do_aliyun_image(
                    api_key=api_key, base_url=base_url, model_id=model_id,
                    prompt=input_text, merged_config=dict(merged_config),
                    ctx=ctx, label=label,
                )
            return await _do_aliyun_video(
                api_key=api_key, base_url=base_url, model_id=model_id,
                prompt=input_text, merged_config=dict(merged_config),
                ctx=ctx, label=label,
            )
        try:
            return await _call_aliyun_once()
        except Exception as exc:
            if not _is_transient_litellm_error(exc):
                raise
            logger.warning(
                "DashScope %s 瞬态错误：%s — sleep %.0fs 后重试一次",
                mode, exc, _IMAGE_RETRY_DELAY_SEC,
            )
            await _asyncio.sleep(_IMAGE_RETRY_DELAY_SEC)
            return await _call_aliyun_once()

    # ── 火山引擎方舟 image：直接 HTTP /api/v3/images/generations ──
    if _is_volcengine(base_url) and mode == "image":
        async def _call_volc_image_once() -> str:
            return await _do_volcengine_image(
                api_key=api_key, base_url=base_url, model_id=model_id,
                prompt=input_text, merged_config=dict(merged_config),
            )
        try:
            return await _call_volc_image_once()
        except Exception as exc:
            if not _is_transient_litellm_error(exc):
                raise
            logger.warning(
                "Volcengine image 瞬态错误：%s — sleep %.0fs 后重试一次",
                exc, _IMAGE_RETRY_DELAY_SEC,
            )
            await _asyncio.sleep(_IMAGE_RETRY_DELAY_SEC)
            return await _call_volc_image_once()

    # ── 火山引擎方舟 video：异步任务接口 /api/v3/contents/generations/tasks ──
    if _is_volcengine(base_url) and mode == "video":
        try:
            return await _do_volcengine_video(
                api_key=api_key, base_url=base_url, model_id=model_id,
                prompt=input_text, merged_config=dict(merged_config),
                ctx=ctx, label=label,
            )
        except Exception as exc:
            if not _is_transient_litellm_error(exc):
                raise
            logger.warning(
                "Volcengine video 瞬态错误：%s — sleep %.0fs 后重试一次",
                exc, _IMAGE_RETRY_DELAY_SEC,
            )
            await _asyncio.sleep(_IMAGE_RETRY_DELAY_SEC)
            return await _do_volcengine_video(
                api_key=api_key, base_url=base_url, model_id=model_id,
                prompt=input_text, merged_config=dict(merged_config),
                ctx=ctx, label=label,
            )

    # ── Nebula 代理 image：直接 HTTP /v1/images/generations（绕开 litellm 的 model_dump bug）──
    if _is_nebula(base_url) and mode == "image":
        async def _call_nebula_image_once() -> str:
            return await _do_nebula_image(
                api_key=api_key, base_url=base_url, model_id=model_id,
                prompt=input_text, merged_config=dict(merged_config),
            )
        try:
            return await _call_nebula_image_once()
        except Exception as exc:
            if not _is_transient_litellm_error(exc):
                raise
            logger.warning(
                "Nebula image 瞬态错误：%s — sleep %.0fs 后重试一次",
                exc, _IMAGE_RETRY_DELAY_SEC,
            )
            await _asyncio.sleep(_IMAGE_RETRY_DELAY_SEC)
            return await _call_nebula_image_once()

    # ── Nebula 代理 video：走自定义 /v1/video/generations 异步流（含 Seedance / Hailuo / Wan-t2v）──
    if _is_nebula(base_url) and mode == "video":
        try:
            return await _do_nebula_video(
                api_key=api_key, base_url=base_url, model_id=model_id,
                prompt=input_text, merged_config=dict(merged_config),
                ctx=ctx, label=label,
            )
        except Exception as exc:
            if not _is_transient_litellm_error(exc):
                raise
            logger.warning(
                "Nebula video 瞬态错误：%s — sleep %.0fs 后重试一次",
                exc, _IMAGE_RETRY_DELAY_SEC,
            )
            await _asyncio.sleep(_IMAGE_RETRY_DELAY_SEC)
            return await _do_nebula_video(
                api_key=api_key, base_url=base_url, model_id=model_id,
                prompt=input_text, merged_config=dict(merged_config),
                ctx=ctx, label=label,
            )

    async def _call_image_once() -> str:
        return await _do_image(
            litellm=litellm, route=route, api_key=api_key,
            api_base=api_base, input_text=input_text, merged_config=merged_config,
        )

    if mode == "image":
        try:
            return await _call_image_once()
        except Exception as exc:
            if not _is_transient_litellm_error(exc):
                raise
            logger.warning(
                "invoke_aux_model image 瞬态错误：%s — sleep %.0fs 后重试一次",
                exc, _IMAGE_RETRY_DELAY_SEC,
            )
            await _asyncio.sleep(_IMAGE_RETRY_DELAY_SEC)
            return await _call_image_once()

    if mode == "video":
        # 非 aliyun / 非 nebula / 非 volcengine provider 的 video 路径暂未实现
        return (
            f"❌ video 模式当前仅 aliyun / nebula / volcengine 已实现。"
            f"当前 provider base_url={base_url}，请联系研发接入对应厂商。"
        )

    if mode == "embedding":
        resp = await litellm.aembedding(
            model=route,
            input=input_text,
            api_key=api_key,
            api_base=api_base,
            **merged_config,
        )
        data = resp.get("data") if isinstance(resp, dict) else getattr(resp, "data", None)
        vec = []
        if data and len(data) > 0:
            item = data[0]
            vec = (
                item.get("embedding") if isinstance(item, dict) else getattr(item, "embedding", [])
            )
        return (
            f"embedding 维度={len(vec)}；前 5 维：{vec[:5] if vec else '[]'}；"
            f"平均绝对值 {sum(abs(x) for x in (vec or [0])) / max(len(vec), 1):.4f}"
        )

    # 默认 chat
    resp = await litellm.acompletion(
        model=route,
        messages=[{"role": "user", "content": input_text}],
        api_key=api_key,
        api_base=api_base,
        **merged_config,
    )
    choices = resp.get("choices") if isinstance(resp, dict) else getattr(resp, "choices", [])
    if choices:
        msg = choices[0]
        m = (msg.get("message") if isinstance(msg, dict) else getattr(msg, "message", None)) or {}
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        return str(content)
    return str(resp)


def invoke_aux_model_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _invoke(
        alias_or_role: str,
        input: str,
        mode: str | None = None,
        config_overrides: dict | None = None,
    ) -> str:
        binding, err = await _resolve_binding(ctx, alias_or_role)
        if err:
            return err
        assert binding is not None

        # 推断默认 mode
        resolved_mode = mode or _default_mode(binding["role"], binding["model_type"])
        merged_config = {**(binding.get("config") or {}), **(config_overrides or {})}

        try:
            out = await _invoke_litellm(
                provider_type=binding["provider_type"],
                base_url=binding.get("base_url"),
                api_key=binding["api_key"],
                model_id=binding["model_id"],
                mode=resolved_mode,
                input_text=input,
                merged_config=merged_config,
                ctx=ctx,
                label=None,
            )
        except Exception as exc:
            logger.exception("invoke_aux_model 调用失败")
            # 检测是否永久错误；是的话明确告知 LLM 不要重试同输入
            hint = _classify_error_brief(str(exc))
            if hint or _is_non_retriable_error(exc):
                return f"⛔ 调用失败（不可重试）：{hint or '永久错误，必须改输入'}\n  原始错误：{str(exc)[:300]}"
            return f"❌ 调用失败：{exc}"

        logger.info(
            "🧩 invoke_aux_model: alias=%s role=%s mode=%s -> %d chars",
            binding.get("alias"),
            binding["role"],
            resolved_mode,
            len(out),
        )
        return out

    return StructuredTool.from_function(
        coroutine=_invoke,
        name="invoke_aux_model",
        description=(
            "调用 Agent 绑定的辅助模型。**必须显式传 alias_or_role 与 mode**。\n"
            "参数：\n"
            "- alias_or_role(str)：**优先传 role 名**（'image' / 'video' / 'embedding' / 'chat'）按 role 兜底匹配第一条；\n"
            "  也可传 Agent 后台配的 alias 字面值（如 'banana' / 'banana pro'），但 alias 命名因人而异，写 role 最稳。\n"
            "- input(str)：给目标模型的输入。image / video 模式 → 视觉描述（不要写「请生成」「请返回 URL」等对话语）；\n"
            "  embedding 模式 → 待嵌入文本；chat 模式 → 普通对话。\n"
            "- mode(str, 可选: chat|image|video|embedding)：**显式指定**模式；省略时按 role 推断。\n"
            "  画图必须 `mode=\"image\"`，生视频必须 `mode=\"video\"`；不要因为 alias 名字像就写 chat。\n"
            "- config_overrides(dict, 可选)：透传给上游 API（size / n / duration / seed / negative_prompt 等）。\n"
            "  阿里 video 还支持 `img_url`（图生视频起始帧）/ `last_frame_url`（首尾帧补帧）。\n"
            "\n"
            "正确示例（画一张参考图）：\n"
            "  invoke_aux_model(alias_or_role='image', mode='image',\n"
            "    input='Product render of a panda toy, soft matte finish, front 3/4 view, white background.')\n"
            "\n"
            "正确示例（5 秒文生视频）：\n"
            "  invoke_aux_model(alias_or_role='video', mode='video',\n"
            "    input='A cinematic shot of a panda walking in a bamboo forest, slow camera dolly.',\n"
            "    config_overrides={'size': '1280*720', 'duration': 5})\n"
            "\n"
            "正确示例（图生视频 i2v —— 给一张参考图，模型据此做动画）：\n"
            "  invoke_aux_model(alias_or_role='video', mode='video',\n"
            "    input='Camera slowly zooms in on the bluetooth icon, soft glow expands',\n"
            "    config_overrides={'image_url': 'https://.../first-frame.png', 'duration': 5})\n"
            "  注：i2v 模型（wan2.6-i2v / seedance-*-i2v / hailuo i2v 等）**必须**传 image_url；\n"
            "  字段名统一用 `image_url`，工具自动映射到各家原生字段（nebula→image / aliyun→img_url / volcengine→content.image_url）。\n"
            "\n"
            "🚨 **duration 必须查模型支持的值**（不合法时工具会拒绝提交并返回提示）：\n"
            "  - Seedance 2.0 全系（含 fast）/ Wan2.6 全系 / Wan2.5：仅支持 5 或 10 秒\n"
            "  - MiniMax-Hailuo 全系：仅支持 6 秒\n"
            "  - **用户要长视频（>10s）→ 拆成 N 个 5/10 秒片段分别生成**，最后多 artifact 落地让前端按顺序播；\n"
            "    **严禁** 直接传 duration=20 / 30 等非法值反复重试（上游必 400，LLM 自闭循环到 max_iter）\n"
            "\n"
            "image 模式遇到 `Connection reset by peer` 工具内部会延迟 8s 自动重试一次；仍失败请简化 prompt 再调。\n"
            "video 任务通常 30-180 秒，工具内部异步轮询（最长 240s 阿里 / 360s nebula / 480s volcengine），耐心等待。"
        ),
    )


def parallel_invoke_aux_model_tool(ctx: BuiltinToolContext) -> StructuredTool:
    """批量并行调辅助模型。同一辅助模型角色，N 个不同 prompt（如 N 个分镜），
    并行 asyncio.gather 提交；任何 slot 命中限流/瞬态错误时，等其它 slot 完成后再重试。
    """
    async def _parallel(
        alias_or_role: str,
        items: list[dict],
        mode: str | None = None,
    ) -> str:
        if not items or not isinstance(items, list):
            return "❌ items 必须是非空 list[dict]"
        binding, err = await _resolve_binding(ctx, alias_or_role)
        if err:
            return err
        assert binding is not None
        resolved_mode = mode or _default_mode(binding["role"], binding["model_type"])

        async def _one(idx: int, it: dict) -> tuple[int, bool, str]:
            if not isinstance(it, dict):
                return idx, False, f"❌ items[{idx}] 不是 dict"
            input_text = it.get("input")
            if not input_text:
                return idx, False, f"❌ items[{idx}] 缺 input"
            cfg = {**(binding.get("config") or {}), **(it.get("config_overrides") or {})}
            label = it.get("label") or f"item_{idx+1}"
            try:
                out = await _invoke_litellm(
                    provider_type=binding["provider_type"],
                    base_url=binding.get("base_url"),
                    api_key=binding["api_key"],
                    model_id=binding["model_id"],
                    mode=resolved_mode,
                    input_text=input_text,
                    merged_config=cfg,
                    ctx=ctx,
                    label=label,
                )
                return idx, True, out
            except Exception as exc:
                return idx, False, f"{type(exc).__name__}: {exc}"

        # 第一轮：全部并行
        round1_tasks = [_one(i, it) for i, it in enumerate(items)]
        results1 = await asyncio.gather(*round1_tasks)

        retry_slots: list[tuple[int, dict]] = []
        finals: dict[int, tuple[bool, str]] = {}
        for idx, ok, msg in results1:
            if ok:
                finals[idx] = (True, msg)
                continue
            msg_lower = msg.lower()
            if any(k in msg_lower for k in _NON_RETRIABLE_KEYWORDS):
                hint = _classify_error_brief(msg) or "永久错误，禁止重试同输入"
                finals[idx] = (False, f"⛔ 不可重试：{hint}\n  原始错误：{msg[:300]}")
                continue
            if any(k in msg_lower for k in ("429", "ratelimit", "rate limit",
                                            "too many", "503", "502", "504",
                                            "internalservererror", "timeout")):
                retry_slots.append((idx, items[idx]))
            else:
                finals[idx] = (False, f"⚠️ 未知错误（不自动重试）：{msg[:300]}")

        # 第二轮：sleep 后重试瞬态失败的 slot
        if retry_slots:
            logger.info("parallel_invoke_aux_model: %d 个 slot 命中瞬态错误，准备重试", len(retry_slots))
            await asyncio.sleep(_IMAGE_RETRY_DELAY_SEC)
            round2_tasks = [_one(i, it) for i, it in retry_slots]
            results2 = await asyncio.gather(*round2_tasks)
            for idx, ok, msg in results2:
                finals[idx] = (ok, msg)

        ordered = [finals[i] for i in range(len(items))]
        ok_count = sum(1 for ok, _ in ordered if ok)
        lines = [f"## parallel_invoke_aux_model 结果（{ok_count}/{len(items)} 成功）"]
        for i, (ok, msg) in enumerate(ordered):
            label = items[i].get("label") or f"item_{i+1}"
            mark = "✅" if ok else "❌"
            lines.append(f"\n### {mark} [{i+1}/{len(items)}] {label}")
            lines.append(msg[:600])
        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_parallel,
        name="parallel_invoke_aux_model",
        description=(
            "**批量并行**调辅助模型。同一辅助模型角色 + N 个不同 prompt 一次提交，"
            "适合多分镜视频、多视图图像、多组件批量生成等场景。\n"
            "参数：\n"
            "- alias_or_role(str)：同 invoke_aux_model（建议传 role 名 'image' / 'video'）\n"
            "- items(list[dict])：每条 `{input: str, config_overrides?: dict, label?: str}`；\n"
            "  label 用于结果聚合时区分（如 '镜头01_明星代言'），可选\n"
            "- mode(str, 可选: chat|image|video|embedding)：同 invoke_aux_model\n"
            "\n"
            "**特性**：\n"
            "1. 并行：asyncio.gather 同时提交 N 个任务（4 段视频从 12 分钟压到 3-4 分钟）\n"
            "2. 限流自愈：第一轮任何 slot 命中 429/瞬态错误时，等其它 task 完成后自动重试 1 次\n"
            "3. 永久错误识别：⛔ 不可重试前缀的 slot LLM 必须跳过，绝不能用同一输入再调一次\n"
            "4. 进度透传：每个 slot 内部 emit data-aux-task-progress 事件，前端按 task_id 分别显示进度\n"
            "\n"
            "结果标记：\n"
            "- ✅ 成功 → 提取 URL 加入 workspace_write_batch\n"
            "- ⛔ 不可重试 → 跳过该 slot 并报告\n"
            "- ❌ 未知错误 → 最多自己改 prompt 重试 1 次该 slot"
        ),
    )


def _default_mode(role: str, model_type: str) -> str:
    if role == "image" or model_type == "image":
        return "image"
    if role == "video" or model_type == "video":
        return "video"
    if role in ("embedding", "rerank") or model_type == "embedding":
        return "embedding"
    return "chat"
