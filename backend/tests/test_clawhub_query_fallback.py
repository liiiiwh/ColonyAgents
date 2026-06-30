"""clawhub_search 自动放宽：ClawHub 是全 token AND 匹配，LLM 堆形态词（MCP/publish/post）会命中 0。
_clawhub_query_fallbacks 生成由窄到宽的候选，保证既有 skill 不被漏掉而误判"平台没有"。
"""
from app.skills_builtin.channel.clawhub_skills import _clawhub_query_fallbacks


def test_drops_noise_tokens_then_narrows():
    # Builder 实测 0 命中的查询 → 先剔噪声词到领域词，再收到单领域词
    fb = _clawhub_query_fallbacks("zhihu 知乎 MCP publish post comment")
    assert fb[0] == "zhihu 知乎 MCP publish post comment"  # 先试原词
    assert "zhihu 知乎" in fb                                # 剔掉 MCP/publish/post/comment
    assert fb[-1] == "zhihu"                                 # 最宽：单领域词


def test_single_term_no_extra_candidates():
    assert _clawhub_query_fallbacks("zhihu") == ["zhihu"]


def test_clean_query_unchanged_no_dupes():
    # 已经是干净领域词组（无噪声）→ 不重复塞同样的候选
    fb = _clawhub_query_fallbacks("知乎 发帖")
    assert fb[0] == "知乎 发帖"
    assert len(fb) == len(set(fb))  # 去重保序


def test_all_noise_falls_back_to_original_only():
    # 全是形态词（无领域词）→ 没法收窄，至少保留原查询不报错
    fb = _clawhub_query_fallbacks("http api browser automation")
    assert fb[0] == "http api browser automation"
    assert len(fb) >= 1
