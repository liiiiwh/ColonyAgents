"""ADR-025 follow-up · worker 线程标题：显示 worker 名/slug，绝不暴露裸 uuid。

存在的 worker → agent 名（capability）；已删 worker → 「Worker · 短id（已删除）」（不暴露
双 uuid 的裸 thread_key）；真畸形键 → 兜底原键。
"""
from app.api.observe import _worker_thread_title


def test_existing_worker_shows_label():
    assert _worker_thread_title(
        "worker:abc:def", "def", "Catalog Worker · Data Fetching（data_fetcher）"
    ) == "Catalog Worker · Data Fetching（data_fetcher）"


def test_deleted_worker_shows_short_id_not_raw_thread_key():
    tk = "worker:37283ba4-a11c-490f-bf58-24b5cb55e261:d3e5753c-677c-4995-beda-c4103cb28839"
    title = _worker_thread_title(tk, "d3e5753c-677c-4995-beda-c4103cb28839", None)
    assert title.startswith("Worker · d3e5753c")
    assert "已删除" in title
    assert "37283ba4" not in title  # 不暴露 super_id
    assert title != tk  # 绝不裸 thread_key


def test_malformed_falls_back_to_key():
    assert _worker_thread_title("weird-key", None, None) == "weird-key"
