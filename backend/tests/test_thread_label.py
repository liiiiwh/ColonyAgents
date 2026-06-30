"""S3/ADR-024 #8 · worker 线程显示可读名而非 UUID。

_worker_id_from_thread_key 从 worker:{super}:{worker} 提取 worker_id（全 UUID），
super_threads 据此查 agent.name + capability 填 title。
"""

from __future__ import annotations

from app.api.observe import _worker_id_from_thread_key


def test_extract_worker_id():
    assert _worker_id_from_thread_key("worker:11111111-aaaa:22222222-bbbb") == "22222222-bbbb"


def test_main_and_health_have_no_worker_id():
    assert _worker_id_from_thread_key("main") is None
    assert _worker_id_from_thread_key("health") is None


def test_malformed_returns_none():
    assert _worker_id_from_thread_key("worker:onlyone") is None
    assert _worker_id_from_thread_key("") is None
    assert _worker_id_from_thread_key("worker:") is None
