"""对象存储管理 API。

两类使用者：
- 管理员（Admin）：全部 key 的管理（list / upload / download / delete / presigned）
- 普通用户（User）：只能通过 `POST /api/storage/user-upload` 上传自己的聊天附件，
  服务器强制 key 前缀为 `users/{user_id}/{yyyymm}/{uuid}-{filename}`，并返回签名 URL。
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.core.config import settings
from app.core.deps import AdminUser, CurrentUser
from app.schemas.storage import PresignedUrlResponse, StorageObject, UploadResponse
from app.services.storage_service import get_storage

logger = logging.getLogger(__name__)

# Anthropic Claude 视觉上限：单图 base64 ≤ 5 MB（≈ raw ≤ 3.75 MB），分辨率 ≤ 1.15 MP。
# 超过任一阈值，Bedrock 会返 400。上传时把超规图自动缩到限制内 + JPEG 重压。
_VISION_RAW_MAX = int(3.5 * 1024 * 1024)  # 留 0.25 MB 安全冗余
_VISION_LONGEST_EDGE = 1568  # ~1568×1568 ≈ 2.46 MP；先按边长缩，再按字节缩

router = APIRouter(prefix="/api/storage", tags=["storage"])


# ──────────────────── Admin 入口 ────────────────────
@router.get("/files", response_model=list[StorageObject])
async def list_files(_: AdminUser, prefix: str = "") -> list[StorageObject]:
    storage = get_storage()
    items = await storage.list_objects(prefix)
    return [StorageObject(**i) for i in items]


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    _: AdminUser,
    file: UploadFile = File(...),
    key: str | None = None,
) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="缺少文件名")
    key = key or file.filename
    body = await file.read()
    storage = get_storage()
    await storage.upload(key, body, content_type=file.content_type or "application/octet-stream")
    return UploadResponse(
        key=key, size=len(body), content_type=file.content_type or "application/octet-stream"
    )


@router.get("/download")
async def download_file(_: AdminUser, key: str = Query(...)) -> Response:
    storage = get_storage()
    try:
        body = await storage.download(key)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="文件不存在") from exc
    return Response(content=body, media_type="application/octet-stream")


@router.get("/url", response_model=PresignedUrlResponse)
async def presigned_url(_: AdminUser, key: str = Query(...)) -> PresignedUrlResponse:
    storage = get_storage()
    url = await storage.presigned_url(key, expires_in=settings.S3_PRESIGNED_URL_EXPIRE)
    return PresignedUrlResponse(url=url, expires_in=settings.S3_PRESIGNED_URL_EXPIRE)


@router.get("/refresh-url", response_model=PresignedUrlResponse)
async def refresh_user_url(
    user: CurrentUser, key: str = Query(..., description="S3 key")
) -> PresignedUrlResponse:
    """用户对自己 session 产生的 S3 key 重签。
    key 必须在 `colony/workspace/` 或 `users/<user_id>/` 前缀下。
    """
    if not key.startswith("colony/workspace/") and not key.startswith(
        f"users/{user.id}/"
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="无权为该 key 生成签名 URL"
        )
    storage = get_storage()
    url = await storage.presigned_url(key, expires_in=settings.S3_PRESIGNED_URL_EXPIRE)
    return PresignedUrlResponse(url=url, expires_in=settings.S3_PRESIGNED_URL_EXPIRE)


@router.delete("/files", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(_: AdminUser, key: str = Query(...)) -> None:
    storage = get_storage()
    await storage.delete(key)


# ─── 公网代理 ──────────────────────────────────────────────
# 用途：私有 S3（如 bj.s3.qiyi.storage）没开 CORS，浏览器 fetch / model-viewer 等
# 需要预检的资源加载会被拦。这里做一层后端反向代理：用户带着 s3_key 来，后端内网拉
# S3 → 携带 CORS 头流回前端。
# 安全：s3_key 内嵌 UUID 几乎不可猜测，与 presigned URL 同等容量级；只允许 `colony/`
# 前缀防止越权读其它 bucket 路径；不要求登录态（避开 model-viewer fetch 不带 token 的问题）。
# 桶内相对 key 的白名单前缀（bucket=colony）。产物 key 形如 aux-image/... / workspace/... ，
# **不含**桶名；前端展示 URL 的 path 是 /colony/aux-image/...，proxy 会先剥掉 colony/ 桶前缀再校验。
_ALLOWED_PROXY_PREFIXES = ("aux-image/", "workspace/", "deliverables/", "users/")
_PROXY_CT_BY_EXT = {
    "glb": "model/gltf-binary",
    "gltf": "model/gltf+json",
    "fbx": "application/octet-stream",
    "usdz": "model/vnd.usdz+zip",
    "obj": "text/plain",
    "mtl": "text/plain",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "json": "application/json",
}


@router.get("/proxy")
async def proxy_object(key: str = Query(..., description="S3 key, must start with allowed prefix")) -> Response:
    """匿名反向代理 S3 对象，附带宽松 CORS 与正确 Content-Type，让 model-viewer 等
    需要 CORS 预检的浏览器 API 能跨域加载内网 S3 资源。
    """
    # 前端展示 URL 的 path 形如 /colony/aux-image/...（colony=桶名）；真实 S3 key 是桶内相对路径
    # aux-image/...。剥掉可选的 colony/ 桶前缀再校验+下载，前端无论传哪种形式都能用。
    rel_key = key[len("colony/"):] if key.startswith("colony/") else key
    if not any(rel_key.startswith(p) for p in _ALLOWED_PROXY_PREFIXES):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="key 必须以白名单前缀开头"
        )
    storage = get_storage()
    try:
        body = await storage.download(rel_key)
    except Exception as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"对象不存在或下载失败：{exc}") from exc
    ext = rel_key.rsplit(".", 1)[-1].lower() if "." in rel_key else ""
    content_type = _PROXY_CT_BY_EXT.get(ext, "application/octet-stream")
    return Response(
        content=body,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=3600",
            # 多 CORS 头让浏览器满意（FastAPI 顶层 CORSMiddleware 也会加，但这里冗余更稳）
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )


# ──────────────────── User 端上传入口 ────────────────────
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_name(name: str) -> str:
    """去掉 / 以及不安全字符，最长 96。"""
    base = name.rsplit("/", 1)[-1]
    safe = _SAFE_NAME_RE.sub("_", base)[:96]
    return safe or "file"


class UserUploadResponse(UploadResponse):
    url: str
    expires_in: int


def _shrink_image_for_vision(body: bytes, mime: str) -> tuple[bytes, str, str]:
    """图像超出 Anthropic Claude 视觉上限时缩到 ≤ 3.5 MB raw / 长边 ≤ 1568 px。

    返回 `(new_body, new_mime, new_ext)`。无需缩或不是图像，原样返回。
    输出统一 JPEG（透明 PNG 也压扁，因为 Claude 视觉只识图，不需要透明通道；并且能省更多体积）。
    缩不下来抛 ValueError，让调用方返 4xx 让用户知道。
    """
    if not mime or not mime.startswith("image/"):
        return body, mime, ""
    if len(body) <= _VISION_RAW_MAX:
        # 字节数 OK，再校验长边（极端情况：JPEG 极致压缩但分辨率超 4K，base64 后可能仍超 5 MB）
        try:
            from PIL import Image
            with Image.open(io.BytesIO(body)) as img:
                w, h = img.size
            if max(w, h) <= _VISION_LONGEST_EDGE:
                return body, mime, ""
        except Exception:
            return body, mime, ""
    # 进入缩图分支
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow 未安装，无法缩图；放行原始 %d bytes（可能被 LLM 拒）", len(body))
        return body, mime, ""

    try:
        with Image.open(io.BytesIO(body)) as img:
            # 转 RGB（移除 alpha；JPEG 不支持透明）
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            w, h = img.size
            longest = max(w, h)
            if longest > _VISION_LONGEST_EDGE:
                ratio = _VISION_LONGEST_EDGE / longest
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            # 尝试递减 quality 直到 ≤ 3.5 MB
            for q in (85, 75, 65, 55, 45):
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=q, optimize=True)
                if buf.tell() <= _VISION_RAW_MAX:
                    out = buf.getvalue()
                    logger.info(
                        "✂️  图像缩压 %d → %d bytes (q=%d, %dx%d)",
                        len(body), len(out), q, img.size[0], img.size[1],
                    )
                    return out, "image/jpeg", ".jpg"
    except Exception as exc:
        logger.warning("缩图失败,放行原始:%s", exc)
        return body, mime, ""

    raise ValueError(f"图像即便 quality=45 仍超过 {_VISION_RAW_MAX} bytes")


@router.post("/user-upload", response_model=UserUploadResponse)
async def user_upload(
    user: CurrentUser,
    file: UploadFile = File(...),
) -> UserUploadResponse:
    """任意已登录用户上传聊天附件。

    服务器决定 key：`users/{user_id}/{yyyymm}/{uuid}-{safe-filename}`，
    返回预签名 URL 供前端直接拿来作为 attachment.content 传给 chat。

    **图像自动适配 LLM 视觉上限**：超过 3.5 MB 或长边 > 1568 px 时，服务端缩到限内
    （Anthropic Claude 单图 base64 ≤ 5 MB，否则 Bedrock 400）。
    """
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="缺少文件名")
    body = await file.read()
    if len(body) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="文件为空")
    # 限制 20MB，防止内存暴涨；真要更大请改成 direct-to-S3 签名上传
    if len(body) > 20 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件超过 20MB")

    content_type = file.content_type or "application/octet-stream"

    # 图像自动缩压到 LLM 视觉上限内
    safe = _sanitize_name(file.filename)
    try:
        body, content_type, ext_override = _shrink_image_for_vision(body, content_type)
    except ValueError as err:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"图像无法压到 LLM 视觉上限（{_VISION_RAW_MAX // 1024 // 1024} MB）：{err}",
        ) from err
    if ext_override and not safe.lower().endswith(ext_override):
        # 把扩展名换成压缩后的实际格式（jpg），避免下游按 .png 解析却拿到 jpeg 字节
        stem = safe.rsplit(".", 1)[0] if "." in safe else safe
        safe = stem + ext_override

    yyyymm = datetime.now(UTC).strftime("%Y%m")
    key = f"users/{user.id}/{yyyymm}/{uuid.uuid4().hex}-{safe}"

    storage = get_storage()
    await storage.upload(key, body, content_type=content_type)
    url = await storage.presigned_url(key, expires_in=settings.S3_PRESIGNED_URL_EXPIRE)
    return UserUploadResponse(
        key=key,
        size=len(body),
        content_type=content_type,
        url=url,
        expires_in=settings.S3_PRESIGNED_URL_EXPIRE,
    )
