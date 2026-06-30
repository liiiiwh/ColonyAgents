"""Seedream 出图 size 守卫：避免首调 HTTP 400「image size must be at least 3686400 pixels」。

Chrome e2e 实测：电商营销主图 worker 调 doubao-seedream-5-0 时，缺省/过小的 size 被 Ark 拒
（min 3686400 px ≈ 1920x1920），白白浪费一次 API 调用后才重试成功。守卫：seedream 系列在缺
省或过小时补/升到安全默认 2048x2048（4194304 px）；已合规或具名 size（如 '2K'）不动；非
seedream 模型不干预。
"""
from __future__ import annotations

from app.skills_builtin.llm.aux_model_skills import _ensure_image_size, _parse_size_pixels


def test_parse_size_pixels():
    assert _parse_size_pixels("1024x1024") == 1024 * 1024
    assert _parse_size_pixels("1920*1080") == 1920 * 1080
    assert _parse_size_pixels("2K") is None       # 具名尺寸无法解析像素
    assert _parse_size_pixels(None) is None
    assert _parse_size_pixels("") is None


def test_seedream_absent_size_gets_safe_default():
    out = _ensure_image_size("doubao-seedream-5-0-260128", {})
    assert out["size"] == "2048x2048"


def test_seedream_too_small_size_bumped():
    out = _ensure_image_size("doubao-seedream-5-0-260128", {"size": "1024x1024"})
    assert _parse_size_pixels(out["size"]) >= 3_686_400


def test_seedream_valid_size_untouched():
    out = _ensure_image_size("doubao-seedream-4-5-251128", {"size": "2048x2048"})
    assert out["size"] == "2048x2048"


def test_seedream_named_size_untouched():
    out = _ensure_image_size("doubao-seedream-5-0-260128", {"size": "2K"})
    assert out["size"] == "2K"


def test_non_seedream_not_touched():
    # seededit / 其它模型不强加 size（不同接口要求不同）
    out = _ensure_image_size("doubao-seededit-3-0-i2i-250628", {})
    assert "size" not in out
    out2 = _ensure_image_size("aliyun/wan2.7-image", {})
    assert "size" not in out2


def test_seedream_preserves_other_keys():
    out = _ensure_image_size("doubao-seedream-5-0-260128", {"n": 1, "negative_prompt": "blur"})
    assert out["n"] == 1
    assert out["negative_prompt"] == "blur"
    assert out["size"] == "2048x2048"
