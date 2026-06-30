"""M6: ClawHub HTTP API 薄客户端。

文档：
- https://documentation.openclaw.ai/clawhub/api
- https://documentation.openclaw.ai/clawhub/http-api

设计原则：
- 用 httpx.AsyncClient；token 从 settings 读
- 处理 429 / RateLimit-Reset：自动 sleep + 重试 1 次
- 安全前置（security_summary）必查；返回原始 dict，由调用方决定是否拒绝
- 仅封 colony 实际用到的 endpoint：search / skill_detail / security / download
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class ClawHubError(Exception):
    """ClawHub API 调用失败的基类。"""


class ClawHubRateLimited(ClawHubError):
    pass


class ClawHubNotFound(ClawHubError):
    pass


class ClawHubBlocked(ClawHubError):
    """安全前置：scan/moderation 标记为危险或 quarantine。"""


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json", "User-Agent": "colony/0.1"}
    if settings.CLAWHUB_TOKEN:
        h["Authorization"] = f"Bearer {settings.CLAWHUB_TOKEN}"
    return h


@asynccontextmanager
async def _client():
    async with httpx.AsyncClient(
        base_url=settings.CLAWHUB_BASE_URL,
        timeout=20.0,
        headers=_headers(),
        follow_redirects=True,
    ) as c:
        yield c


# 瞬时传输层错误（代理抖动 / 连接重置 / 读超时）→ 退避重试。
# 注意：这些 httpx 异常的 str() 往往为空，直接 str(exc) 会得到 error=""（黑盒），故末次失败时带类型名抛出。
_TRANSIENT_EXC = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
    httpx.TimeoutException,  # 覆盖 Connect/Read/Write/PoolTimeout
)


async def _get(path: str, **kwargs) -> Any:
    """带重试的 GET：瞬时网络错误 + 429 都退避重试（最多 3 次）。返回 .json() 或字节。"""
    attempts = 3
    for attempt in range(attempts):
        try:
            async with _client() as c:
                r = await c.get(path, **kwargs)
        except _TRANSIENT_EXC as exc:
            if attempt < attempts - 1:
                logger.warning("[clawhub] 瞬时 %s path=%s attempt=%d → 退避重试",
                               type(exc).__name__, path, attempt)
                await asyncio.sleep(0.6 * (attempt + 1))
                continue
            # 末次仍失败：带**类型名**抛出（原 exc 多为空串，避免下游 error=""）
            raise ClawHubError(
                f"network error after {attempts} tries: {type(exc).__name__}: "
                f"{exc or '(empty message)'} @ {path}"
            ) from exc
        if r.status_code == 429:
            retry = int(r.headers.get("Retry-After") or r.headers.get("RateLimit-Reset") or 1)
            if attempt < attempts - 1:
                logger.warning("[clawhub] 429 path=%s retry-after=%ss", path, retry)
                await asyncio.sleep(min(retry, 30))
                continue
            raise ClawHubRateLimited(f"429 after retry: {path}")
        if r.status_code == 404 or r.status_code == 410:
            raise ClawHubNotFound(f"{r.status_code} {path}")
        if r.status_code >= 400:
            raise ClawHubError(f"{r.status_code} {path}: {r.text[:200]}")
        ct = (r.headers.get("Content-Type") or "").lower()
        if "json" in ct:
            return r.json()
        return r.content
    raise ClawHubError(f"unreachable after {attempts} tries @ {path}")


# ─────────────────────────── Search & list ───────────────────────────
async def search_skills(
    query: str,
    *,
    highlighted_only: bool = False,
    non_suspicious_only: bool = True,
    limit: int = 20,
) -> dict:
    """`GET /api/v1/search?q=...`。返回原始 JSON（含 results / cursor）。"""
    params = {
        "q": query,
        "highlightedOnly": str(highlighted_only).lower(),
        "nonSuspiciousOnly": str(non_suspicious_only).lower(),
        "limit": limit,
    }
    return await _get("/api/v1/search", params=params)


async def search_packages(
    query: str,
    *,
    family: str | None = None,  # skill / code-plugin / bundle-plugin
    category: str | None = None,
    capability_tag: str | None = None,
    executes_code: bool | None = None,
    limit: int = 20,
) -> dict:
    params: dict[str, Any] = {"q": query, "limit": limit}
    if family:
        params["family"] = family
    if category:
        params["category"] = category
    if capability_tag:
        params["capabilityTag"] = capability_tag
    if executes_code is not None:
        params["executesCode"] = str(executes_code).lower()
    return await _get("/api/v1/packages/search", params=params)


async def get_skill(slug: str) -> dict:
    return await _get(f"/api/v1/skills/{slug}")


async def list_skill_versions(slug: str) -> dict:
    return await _get(f"/api/v1/skills/{slug}/versions")


async def get_package(name: str) -> dict:
    return await _get(f"/api/v1/packages/{name}")


# ─────────────────────────── Security & download ───────────────────────────
async def package_security_summary(name: str, version: str) -> dict:
    return await _get(f"/api/v1/packages/{name}/versions/{version}/security")


async def download_skill_zip(slug: str, version: str | None = None) -> bytes:
    """GET /api/v1/download?slug=...&version=... → 返回 ZIP bytes。"""
    params: dict[str, Any] = {"slug": slug}
    if version:
        params["version"] = version
    return await _get("/api/v1/download", params=params)


async def download_package_zip(name: str, version: str | None = None) -> bytes:
    params: dict[str, Any] = {}
    if version:
        params["version"] = version
    return await _get(f"/api/v1/packages/{name}/download", params=params)


# 用于风险闸口
HIGH_RISK_CAPABILITY_TAGS = {
    "requires-binary",
    "requires-native-deps",
    "requires-os-permission",
    "requires-wallet",
    "can-make-purchases",
    "can-sign-transactions",
    "requires-browser",
    "requires-external-service",
}


def is_blocked(security: dict) -> bool:
    """根据 /security 返回判断是否禁止下载。"""
    trust = (security or {}).get("trust") or {}
    if trust.get("blockedFromDownload"):
        return True
    if trust.get("scanStatus") == "malicious":
        return True
    if trust.get("moderationState") == "revoked":
        return True
    return False


def high_risk_tags_in(version_meta: dict) -> Iterator[str]:
    """从 skill version 元数据中拎出 capabilityTags 与高危集合的交集。"""
    sec = (version_meta or {}).get("security") or {}
    tags = sec.get("capabilityTags") or []
    for t in tags:
        if t in HIGH_RISK_CAPABILITY_TAGS:
            yield t
