"""S4/ADR-024 · super 自管调度护栏（防烧钱）。

validate_schedule：每 mission ≤ N 条、interval ≥ 最小间隔、cron 表达式合法。
"""

from __future__ import annotations

from app.domain.scheduling.schedule_guard import parse_interval_seconds, validate_schedule


def test_parse_interval():
    assert parse_interval_seconds("30s") == 30
    assert parse_interval_seconds("5m") == 300
    assert parse_interval_seconds("2h") == 7200
    assert parse_interval_seconds("1d") == 86400
    assert parse_interval_seconds("bad") is None
    assert parse_interval_seconds("0m") is None


def test_count_limit():
    ok, why = validate_schedule(kind="cron", expr="0 10 * * *", existing_count=5)
    assert ok is False and "上限" in why


def test_interval_too_short():
    ok, why = validate_schedule(kind="interval", expr="30s", existing_count=0)
    assert ok is False and "间隔" in why


def test_interval_ok():
    ok, why = validate_schedule(kind="interval", expr="10m", existing_count=0)
    assert ok is True and why == ""


def test_cron_ok():
    ok, _ = validate_schedule(kind="cron", expr="0 10 * * *", existing_count=0)
    assert ok is True


def test_cron_invalid():
    ok, why = validate_schedule(kind="cron", expr="not-a-cron", existing_count=0)
    assert ok is False and "cron" in why
