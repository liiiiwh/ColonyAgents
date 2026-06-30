"""R3-1 · 上下文压缩 policy · 纯决策函数（从 compression_service.maybe_compress_context 抽出）。

决策与执行分离：should_compress / pick_compressible 不碰 DB / LLM，纯可测。
对应 compression_service.maybe_compress_context 原内联逻辑：
  - `if total_tokens < threshold_tokens: return None`  → should_compress
  - `compressible = msgs[:-keep_recent] if len(msgs) > keep_recent else []`  → pick_compressible
"""
from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def should_compress(*, total_tokens: int, threshold_tokens: int) -> bool:
    """对话 token 估算达到阈值（>=）即应压缩。"""
    return total_tokens >= threshold_tokens


def pick_compressible(msgs: list[T], *, keep_recent: int) -> list[T]:
    """返回应被压缩的消息（保留最近 keep_recent 条）。

    msgs 短于等于 keep_recent → 无可压缩。
    """
    if len(msgs) > keep_recent:
        return msgs[:-keep_recent]
    return []
