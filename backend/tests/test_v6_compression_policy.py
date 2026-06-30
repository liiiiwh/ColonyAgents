"""R3-1 · 压缩 policy 纯函数 · 从 compression_service.maybe_compress_context 抽决策逻辑。

决策（should compress? / 哪些可压）与执行（LLM summarize + 原子写）分离。
policy 纯函数 → 边界单测，不需 LLM / DB mock。
"""
from __future__ import annotations

import pytest


def test_should_compress_below_threshold_false():
    from app.domain.compression.policy import should_compress
    assert should_compress(total_tokens=100, threshold_tokens=1000) is False


def test_should_compress_at_threshold_true():
    """恰好等于阈值 → 压（>= 语义，跟原代码 `< threshold: return None` 一致）。"""
    from app.domain.compression.policy import should_compress
    assert should_compress(total_tokens=1000, threshold_tokens=1000) is True


def test_should_compress_above_threshold_true():
    from app.domain.compression.policy import should_compress
    assert should_compress(total_tokens=5000, threshold_tokens=1000) is True


def test_pick_compressible_keeps_recent():
    """保留最近 keep_recent 条，其余为可压缩。"""
    from app.domain.compression.policy import pick_compressible
    msgs = list(range(10))  # 用 int 占位代表 message
    compressible = pick_compressible(msgs, keep_recent=3)
    assert compressible == [0, 1, 2, 3, 4, 5, 6]  # 前 7 条
    # 最近 3 条 (7,8,9) 不压


def test_pick_compressible_empty_when_fewer_than_keep():
    """消息数 <= keep_recent → 没有可压缩的。"""
    from app.domain.compression.policy import pick_compressible
    msgs = [1, 2]
    assert pick_compressible(msgs, keep_recent=3) == []


def test_pick_compressible_exact_keep_recent():
    from app.domain.compression.policy import pick_compressible
    msgs = [1, 2, 3]
    assert pick_compressible(msgs, keep_recent=3) == []
