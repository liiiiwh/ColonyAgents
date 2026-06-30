"""cand② MemoryStore · 确定性收敛核心（纯函数，零 LLM 成本）。

治实战 bug：supervisor 故障循环里每 tick 写「跳过本轮」，旧 dedup 只比**最后一段**→
夹在中间的重复漏掉 → 一天十几万字符。collapse_into 在**任意位置**识别近重复，折成 ×N。
"""
from app.domain.memory.consolidate import collapse_into, fingerprint


def test_unique_block_appended():
    md, collapsed = collapse_into("", "### 决策 A\n发布了笔记")
    assert collapsed is False
    assert "决策 A" in md


def test_exact_repeat_collapses_not_grows():
    md1, _ = collapse_into("", "### 跳过本轮\n等用户配 MCP")
    md2, collapsed = collapse_into(md1, "### 跳过本轮\n等用户配 MCP")
    assert collapsed is True
    # 不增长：仍只有一段「跳过本轮」，带 ×2 计数
    assert md2.count("跳过本轮") == 1
    assert "×2" in md2 or "x2" in md2.lower()


def test_repeat_of_non_last_block_collapses():
    # bug 复现：重复的是夹在中间那段（旧 dedup 只比最后一段会漏）
    md = "### 跳过本轮\n等 MCP\n\n### 发布成功\n笔记X"
    md2, collapsed = collapse_into(md, "### 跳过本轮\n等 MCP")
    assert collapsed is True
    assert md2.count("跳过本轮") == 1  # 中间那段被折叠，没新增


def test_near_dup_normalized_by_fingerprint():
    # 时间戳 / run-N / uuid 不同但语义相同 → 同指纹 → 折叠
    a = "### [2026-06-01 10:00 UTC] run-3 跳过本轮 branch_id=aaaa1111"
    b = "### [2026-06-02 11:30 UTC] run-9 跳过本轮 branch_id=bbbb2222"
    assert fingerprint(a) == fingerprint(b)
    md2, collapsed = collapse_into(a, b)
    assert collapsed is True


def test_counter_increments_across_repeats():
    md = ""
    for _ in range(5):
        md, _ = collapse_into(md, "### 跳过本轮\n等 MCP")
    assert md.count("跳过本轮") == 1
    assert "×5" in md or "x5" in md.lower()
