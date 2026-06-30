"""cand② MemoryStore · 确定性记忆收敛（纯函数，零 LLM 成本）。

- fingerprint(block)：剥离时间戳 / run-N / uuid / 「第N次」等跨 tick 噪声，得语义指纹。
- collapse_into(existing_md, new_block)：在**任意位置**识别近重复 → 折成「×N（最后见…）」一段
  并移到末尾（保最近性），而非每次追加 → 治「跳过本轮」一天刷十几万字符的实战 bug。

记忆是 `\n\n` 分隔的 event 段；段内多行用单 `\n`。本模块只做确定性折叠；总量超阈值的
LLM 合并 / TTL 剪枝由 MemoryStore 在此之上薄薄一层处理。
"""
from __future__ import annotations

import re

_SEP = "\n\n"
_COUNT_RE = re.compile(r"〔重复 ×(\d+)〕")


def fingerprint(block: str) -> str:
    """语义指纹：归一化会跨 tick 变化但语义相同的噪声。"""
    if not block:
        return ""
    t = block.strip()
    t = _COUNT_RE.sub("", t)                                        # 去掉自己加的计数标记
    t = re.sub(r"\[\d{4}-\d{2}-\d{2}[^\]]*\]", "", t)               # 时间戳
    t = re.sub(r"\brun-\d+\b", "run-X", t)                           # run-N
    t = re.sub(r"\bbranch_id=[a-f0-9-]{8,}", "branch_id=<id>", t)
    t = re.sub(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", "<uuid>", t)
    t = re.sub(r"\b(第|连续)\s*\d+\s*次", r"\1N次", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _split(md: str) -> list[str]:
    return [b for b in (md or "").split(_SEP) if b.strip()]


def _prior_count(block: str) -> int:
    m = _COUNT_RE.search(block or "")
    return int(m.group(1)) if m else 1


def _strip_count(block: str) -> str:
    return _COUNT_RE.sub("", block).rstrip()


def collapse_into(existing_md: str, new_block: str) -> tuple[str, bool]:
    """把 new_block 并入 existing_md：近重复 → 折成 ×N 并移末尾；否则追加。

    返回 (new_md, collapsed)。collapsed=True 表示命中了已有近重复（未净增长度）。
    """
    new_block = (new_block or "").strip()
    if not new_block:
        return existing_md or "", False
    blocks = _split(existing_md)
    new_fp = fingerprint(new_block)

    for i, b in enumerate(blocks):
        if fingerprint(b) == new_fp:
            count = max(_prior_count(b), 1) + 1
            collapsed_block = f"{_strip_count(new_block)}  〔重复 ×{count}〕"
            del blocks[i]
            blocks.append(collapsed_block)       # 移到末尾保最近性
            return _SEP.join(blocks), True

    blocks.append(new_block)
    return _SEP.join(blocks), False
