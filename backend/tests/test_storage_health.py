"""S1 · 对象存储启动健康检查 fail-loud（ADR-023）。

storage_service.health_check() 探活 S3：凭据对/可达 → (True,'ok')；
坏凭据/不可达 → (False, 明确原因)，供启动期显式报错，不再靠 write_artifact 静默降级掩盖。
"""

from __future__ import annotations

import pytest

from app.services import storage_service as ss

pytestmark = pytest.mark.asyncio


async def test_health_check_ok_with_inmemory():
    ss.set_storage(ss.make_inmemory_backend())
    try:
        ok, detail = await ss.health_check()
        assert ok is True
        assert detail == "ok"
    finally:
        ss.set_storage(None)  # type: ignore[arg-type]


async def test_health_check_reports_bad_credentials():
    from botocore.exceptions import ClientError

    class _BadBackend:
        async def list_objects(self, prefix: str = ""):
            raise ClientError(
                {"Error": {"Code": "InvalidAccessKeyId", "Message": "bad key"}},
                "ListObjectsV2",
            )

        async def upload(self, *a, **k): ...
        async def download(self, *a, **k): ...
        async def delete(self, *a, **k): ...
        async def presigned_url(self, *a, **k): ...

    ss.set_storage(_BadBackend())  # type: ignore[arg-type]
    try:
        ok, detail = await ss.health_check()
        assert ok is False
        assert "InvalidAccessKeyId" in detail
    finally:
        ss.set_storage(None)  # type: ignore[arg-type]
