"""S4/ADR-024 · super 自管调度护栏（纯函数）。

super 自己增删改调度时，用这组护栏防烧钱：每 mission 调度数上限、interval 最小间隔、
cron 表达式合法性。纯函数，便于独立测。
"""

from __future__ import annotations

_UNIT_SEC = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval_seconds(expr: str) -> int | None:
    """'30s' / '5m' / '2h' / '1d' → 秒；非法或非正 → None。"""
    expr = (expr or "").strip().lower()
    if len(expr) < 2 or expr[-1] not in _UNIT_SEC:
        return None
    try:
        n = int(expr[:-1])
    except ValueError:
        return None
    if n <= 0:
        return None
    return n * _UNIT_SEC[expr[-1]]


def validate_schedule(
    *,
    kind: str,
    expr: str,
    existing_count: int,
    max_count: int = 5,
    min_interval_sec: int = 300,
) -> tuple[bool, str]:
    """校验一条新调度是否允许。返回 (ok, reason)。

    - existing_count ≥ max_count → 拒（先删再加）
    - interval < min_interval_sec → 拒（防每秒空转烧钱）
    - cron 表达式非法 → 拒
    - event 无频率护栏
    """
    if existing_count >= max_count:
        return False, f"调度数已达上限 {max_count} 条，先删一条再加"
    if kind == "interval":
        sec = parse_interval_seconds(expr)
        if sec is None:
            return False, f"interval 表达式非法：{expr!r}（示例 5m / 2h / 1d）"
        if sec < min_interval_sec:
            return False, f"触发间隔 {sec}s 过短，最小 {min_interval_sec}s（防烧钱）"
        return True, ""
    if kind == "cron":
        try:
            from apscheduler.triggers.cron import CronTrigger
            CronTrigger.from_crontab(expr)
        except Exception as e:  # noqa: BLE001
            return False, f"cron 表达式非法：{expr!r}（{e}）"
        return True, ""
    if kind == "event":
        return True, ""
    return False, f"未知调度 kind：{kind!r}"
