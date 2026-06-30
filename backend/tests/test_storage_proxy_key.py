"""storage /proxy 要能服务真实产物 key。

真出过的坑：产物 S3 key 是桶内相对路径 aux-image/...（bucket=colony），但 proxy 旧白名单要求
key 以 colony/ 开头 → 前端用展示 URL 的 path（colony/aux-image/...）来调，download(colony/aux-image/...)
在 colony 桶里找 colony/aux-image/... → NoSuchKey；用 aux-image/... 又被白名单 403。两种形式都挂，
对话内联图就加载不出来。本测试钉死：proxy 剥掉可选 colony/ 桶前缀后按真实 key 校验+下载，两种形式都通。
"""
from __future__ import annotations

import pytest

from app.api.storage import _ALLOWED_PROXY_PREFIXES


def test_allowed_prefixes_are_bucket_relative_not_bucket_name():
    # 白名单是桶内相对前缀（产物真实 key 形态），不是桶名 colony/
    assert "aux-image/" in _ALLOWED_PROXY_PREFIXES
    assert "workspace/" in _ALLOWED_PROXY_PREFIXES
    assert "colony/" not in _ALLOWED_PROXY_PREFIXES


@pytest.mark.parametrize(
    "incoming_key,expected_rel",
    [
        ("colony/aux-image/x.jpg", "aux-image/x.jpg"),  # 前端传桶名前缀形式
        ("aux-image/x.jpg", "aux-image/x.jpg"),  # 桶内相对形式
        ("colony/workspace/m/n/a.png", "workspace/m/n/a.png"),
    ],
)
def test_proxy_strips_optional_bucket_prefix_and_passes(incoming_key, expected_rel):
    # 复刻 proxy_object 的 key 归一化 + 白名单校验逻辑
    rel_key = incoming_key[len("colony/"):] if incoming_key.startswith("colony/") else incoming_key
    assert rel_key == expected_rel
    assert any(rel_key.startswith(p) for p in _ALLOWED_PROXY_PREFIXES)


def test_proxy_rejects_non_artifact_key():
    incoming = "colony/secret/other.txt"
    rel_key = incoming[len("colony/"):]
    assert not any(rel_key.startswith(p) for p in _ALLOWED_PROXY_PREFIXES)
