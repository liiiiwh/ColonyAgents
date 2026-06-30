"""S3 / MinIO 对象存储封装。

使用 `aiobotocore` 异步客户端。测试环境下通过 `get_storage_backend` 可被依赖注入替换。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageBackend(Protocol):
    """存储后端协议，便于测试环境替换成 InMemory 实现。"""

    async def list_objects(self, prefix: str = "") -> list[dict[str, Any]]: ...
    async def upload(self, key: str, body: bytes, *, content_type: str) -> str: ...
    async def download(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def presigned_url(self, key: str, *, expires_in: int = 900) -> str: ...


# ────────────── 真实 S3 客户端 ──────────────
def _build_s3_config() -> AioConfig:
    """根据 settings.S3_FORCE_PATH_STYLE 构造 botocore 配置。

    对于私有 S3 兼容服务（爱奇艺 / 某些 MinIO 部署 / Ceph），bucket 名若被放到
    Host 前缀（virtual-hosted style，AWS 默认）会导致 DNS 不可达。path 风格把
    bucket 放到 URL path，即 `http://endpoint/bucket/key`。
    """
    return AioConfig(
        s3={"addressing_style": "path" if settings.S3_FORCE_PATH_STYLE else "auto"},
        signature_version="s3v4",
        # ⚠️ 显式清空 proxies —— 阻止 botocore 从 HTTP_PROXY/HTTPS_PROXY env 拾起 proxy。
        # 实测：dev 机上 `HTTPS_PROXY=http://127.0.0.1:7890`（clash 等代理），
        # 导致 PUT 到自建 RustFS (182.92.98.228:9008) 走代理时偶发挂死（百分之十几概率），
        # 复现轨迹：`tool-input-available workspace_write` 后 → S3 PUT 永不返回 → SSE 永挂。
        # S3 直连内网 / 自建对象存储几乎从不需要 proxy，强制清空。
        proxies={},
    )


@asynccontextmanager
async def _s3_client(*, endpoint_url: str | None = None) -> AsyncIterator[Any]:
    session = get_session()
    async with session.create_client(
        "s3",
        endpoint_url=endpoint_url or settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        region_name=settings.S3_REGION,
        config=_build_s3_config(),
    ) as client:
        yield client


class S3Backend:
    async def list_objects(self, prefix: str = "", *, max_keys: int = 5000) -> list[dict[str, Any]]:
        """列出 prefix 下对象。S3 list_objects_v2 单次最多 1000 条，自动分页直到 max_keys 上限。

        max_keys=5000 → 最多 5 次 RTT，覆盖绝大多数后台浏览场景；超出则附带 `__truncated__=True`
        指示前端提示用户「已截断 N 条，请缩小 prefix」。
        """
        out: list[dict[str, Any]] = []
        cont_token: str | None = None
        truncated_at_limit = False
        async with _s3_client() as c:
            while True:
                kwargs: dict[str, Any] = {
                    "Bucket": settings.S3_BUCKET_NAME,
                    "Prefix": prefix,
                    "MaxKeys": min(1000, max_keys - len(out)),
                }
                if cont_token:
                    kwargs["ContinuationToken"] = cont_token
                resp = await c.list_objects_v2(**kwargs)
                for o in resp.get("Contents", []):
                    out.append({
                        "key": o["Key"],
                        "size": o["Size"],
                        "last_modified": o["LastModified"].isoformat(),
                    })
                if not resp.get("IsTruncated"):
                    break
                if len(out) >= max_keys:
                    truncated_at_limit = True
                    break
                cont_token = resp.get("NextContinuationToken")
        # 用 sentinel 第一条携带截断标志（向后兼容：没有时缺省 None）
        if truncated_at_limit and out:
            out[0]["__truncated__"] = True  # type: ignore[typeddict-item]
        return out

    async def upload(self, key: str, body: bytes, *, content_type: str) -> str:
        async with _s3_client() as c:
            await c.put_object(
                Bucket=settings.S3_BUCKET_NAME,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
        return key

    async def download(self, key: str) -> bytes:
        async with _s3_client() as c:
            resp = await c.get_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
            async with resp["Body"] as stream:
                return await stream.read()

    async def delete(self, key: str) -> None:
        async with _s3_client() as c:
            await c.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=key)

    async def presigned_url(self, key: str, *, expires_in: int = 900) -> str:
        # presign 对「浏览器可达」端点签名（SigV4 host 进签名，事后改 host 会破坏签名）；
        # 未配置 public 端点则回退内部端点（本地直跑场景两者一致）。
        endpoint = settings.S3_PUBLIC_ENDPOINT_URL or settings.S3_ENDPOINT_URL
        async with _s3_client(endpoint_url=endpoint) as c:
            return await c.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.S3_BUCKET_NAME, "Key": key},
                ExpiresIn=expires_in,
            )


# ────────────── In-Memory 测试后端 ──────────────
class InMemoryBackend:
    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, str]] = {}

    async def list_objects(self, prefix: str = "") -> list[dict[str, Any]]:
        return [
            {"key": k, "size": len(v[0]), "last_modified": "2026-01-01T00:00:00+00:00"}
            for k, v in self._data.items()
            if k.startswith(prefix)
        ]

    async def upload(self, key: str, body: bytes, *, content_type: str) -> str:
        self._data[key] = (body, content_type)
        return key

    async def download(self, key: str) -> bytes:
        if key not in self._data:
            raise KeyError(key)
        return self._data[key][0]

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def presigned_url(self, key: str, *, expires_in: int = 900) -> str:
        return f"memory://{key}?expires_in={expires_in}"


# ────────────── 单例与依赖注入 ──────────────
_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    if _backend is None:
        _backend = S3Backend()
    return _backend


def set_storage(backend: StorageBackend) -> None:
    """测试或运行时切换。"""
    global _backend
    _backend = backend


def make_inmemory_backend() -> InMemoryBackend:
    return InMemoryBackend()


async def health_check() -> tuple[bool, str]:
    """S1/ADR-023 · 探活对象存储：list 一次。返回 (ok, detail)。

    坏凭据 / bucket 不存在 / 不可达 → (False, 明确原因)。启动期调用并 fail-loud，
    不再让 write_artifact 的静默降级（上传失败仅存 content）掩盖 S3 配置故障。
    """
    try:
        await get_storage().list_objects(prefix="__healthcheck__/")
        return True, "ok"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "?")
        return False, f"S3 {code}: {e}"
    except Exception as e:  # noqa: BLE001 — 任何不可达/解析错都算 unhealthy
        return False, f"S3 unreachable: {type(e).__name__}: {e}"


__all__ = [
    "ClientError",
    "InMemoryBackend",
    "S3Backend",
    "StorageBackend",
    "get_storage",
    "health_check",
    "make_inmemory_backend",
    "set_storage",
]
