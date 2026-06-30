"""上传/下载 presigned URL 必须对「浏览器可达」端点签名，而不是内部 S3_ENDPOINT_URL。

bug：docker 里 S3_ENDPOINT_URL=http://minio:9000（容器内网名），presigned_url 直接对它签名，
浏览器拿到 http://minio:9000/... 根本打不开。修：配置 S3_PUBLIC_ENDPOINT_URL（如
http://localhost:19000）后，presign 用它签名（SigV4 的 host 进签名，必须签 public host）。
"""
import pytest

from app.core.config import settings
from app.services.storage_service import S3Backend


@pytest.mark.asyncio
async def test_presigned_url_uses_public_endpoint_when_set(monkeypatch):
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setattr(settings, "S3_PUBLIC_ENDPOINT_URL", "http://localhost:19000")
    url = await S3Backend().presigned_url("users/abc/img.png", expires_in=900)
    assert url.startswith("http://localhost:19000/"), url
    assert "minio:9000" not in url, url
    # 仍是有效 presigned（带签名参数）
    assert "X-Amz-Signature=" in url


@pytest.mark.asyncio
async def test_presigned_url_falls_back_to_internal_when_public_unset(monkeypatch):
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setattr(settings, "S3_PUBLIC_ENDPOINT_URL", "")
    url = await S3Backend().presigned_url("users/abc/img.png", expires_in=900)
    assert url.startswith("http://minio:9000/"), url
