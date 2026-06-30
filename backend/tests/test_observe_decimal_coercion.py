"""observe stats 端点把 Postgres NUMERIC(Decimal)聚合转成 JSON 数字。

回归 bug：worker_stats / super_stats 直接 dict(row) 返回，AVG/SUM/percentile 的 Decimal
被 FastAPI 序列化成字符串（"22405.000000000000"、"0E-20"），前端对字符串调 .toFixed()
直接抛错 → worker 观察页「性能 & 失败分析」点开崩溃。_jnum/_jrow 在端点层把 Decimal 转成
int/float，保证发出的是 JSON 数字。
"""
from __future__ import annotations

import json
from decimal import Decimal

from app.api.observe import _jnum, _jrow


def test_jnum_decimal_integer_to_int():
    assert _jnum(Decimal("22405.000000000000")) == 22405
    assert isinstance(_jnum(Decimal("22405.000000000000")), int)


def test_jnum_decimal_zero_scientific_to_int():
    # AVG over zero tokens → Postgres Decimal('0E-20'); must not stay a string
    assert _jnum(Decimal("0E-20")) == 0
    assert isinstance(_jnum(Decimal("0E-20")), int)


def test_jnum_decimal_fractional_to_float():
    assert _jnum(Decimal("12.5")) == 12.5
    assert isinstance(_jnum(Decimal("12.5")), float)


def test_jnum_passthrough_non_decimal():
    assert _jnum(None) is None
    assert _jnum(3) == 3
    assert _jnum("get_tech_trending") == "get_tech_trending"


def test_jrow_coerces_all_decimals_and_is_json_serializable():
    row = {
        "action": "get_tech_trending",
        "cnt": 3,
        "ok": 1,
        "avg_ms": Decimal("22405.000000000000"),
        "avg_tokens": Decimal("0E-20"),
        "artifact_bytes": Decimal("0"),
    }
    out = _jrow(row)
    # no Decimal survives → json.dumps must not emit a quoted number
    s = json.dumps(out)
    assert '"22405' not in s  # avg_ms is a bare number, not a string
    assert out["avg_ms"] == 22405
    assert out["avg_tokens"] == 0
    assert out["artifact_bytes"] == 0
    assert out["action"] == "get_tech_trending"
