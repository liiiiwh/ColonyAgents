"""thinking_policy 纯函数 · per-family 思考档位（thinking_level）映射。

输入 (level, provider_type, model_id, route) → model_kwargs dict。
档位 off/low/medium/high 按主模型家族映射成各家具体参数：
  - gemini:   thinkingBudget = 0 / 512 / 2048 / 8192（Pro 系下限 128）
  - claude:   thinking.budget_tokens = disabled / 2000 / 8000 / 16000
  - 其它:     reasoning_effort = low / low / medium / high

矩阵：claude / gemini-native / gemini-proxy / doubao / qwen3 / native-openai / deepseek。

★ 修复 R3 flagged bug：native openai（provider_type='openai'）→ 顶层 reasoning_effort；
  仅 openai-compat 代理（custom/dashscope/volcengine/aliyun）才走 extra_body。
"""
from __future__ import annotations


def _compute(level, provider_type, model_id, route):
    from app.domain.llm.thinking_policy import compute_thinking_model_kwargs
    return compute_thinking_model_kwargs(
        level=level,
        provider_type=provider_type,
        model_id=model_id,
        route=route,
    )


# ── off：注入"最严格关闭" ──────────────────────────────────────────────

def test_claude_off_disabled_thinking_plus_stream():
    mk = _compute("off", "anthropic", "claude-opus-4-8", "anthropic/claude-opus-4-8")
    assert mk["thinking"] == {"type": "disabled"}
    assert mk["extra_body"] == {"stream": True}
    assert "reasoning_effort" not in mk


def test_claude_via_custom_proxy_same_as_native():
    """custom 代理 Claude（model_id=claude-*）→ 同 native Claude 处理。"""
    mk = _compute("off", "custom", "claude-sonnet-4-6", "claude-sonnet-4-6")
    assert mk["thinking"] == {"type": "disabled"}
    assert mk["extra_body"] == {"stream": True}


def test_gemini_native_pro_off_uses_min_budget():
    mk = _compute("off", "gemini", "gemini-3.1-pro-preview", "gemini/gemini-3.1-pro-preview")
    assert mk["extra_body"]["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 128


def test_gemini_native_flash_off_budget_zero():
    mk = _compute("off", "gemini", "gemini-flash-lite", "gemini/gemini-flash-lite")
    assert mk["extra_body"]["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0


def test_gemini_via_proxy_off_uses_extra_body_reasoning():
    mk = _compute("off", "custom", "gemini-3-pro", "openai/gemini-3-pro")
    assert mk["extra_body"]["reasoning_effort"] == "low"
    assert "generationConfig" in mk["extra_body"]


def test_doubao_proxy_off_disabled_thinking():
    mk = _compute("off", "custom", "doubao-pro", "openai/doubao-pro")
    assert mk["extra_body"] == {"thinking": {"type": "disabled"}}


def test_qwen3_proxy_off_enable_thinking_false():
    mk = _compute("off", "aliyun", "qwen3-plus", "openai/qwen3-plus")
    assert mk["extra_body"]["reasoning_effort"] == "low"
    assert mk["extra_body"]["enable_thinking"] is False


def test_native_openai_off_uses_TOP_LEVEL_reasoning_effort():
    """★ native openai → 顶层 reasoning_effort，不进 extra_body。"""
    mk = _compute("off", "openai", "gpt-4o-mini", "openai/gpt-4o-mini")
    assert mk.get("reasoning_effort") == "low"
    assert "extra_body" not in mk
    assert "thinking" not in mk


def test_proxy_openai_compat_non_claude_off_uses_extra_body():
    mk = _compute("off", "custom", "some-7b-model", "openai/some-7b-model")
    assert mk["extra_body"]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in mk  # 顶层没有，只在 extra_body


def test_deepseek_off_disabled_via_extra_body_thinking():
    mk = _compute("off", "openai", "deepseek-v4-pro", "openai/deepseek-v4-pro")
    assert mk["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in mk
    assert "thinking" not in mk  # 不混顶层 thinking（那是 Claude 的形态）


def test_deepseek_compat_proxy_off_also_extra_body_thinking():
    mk = _compute("off", "aliyun", "deepseek-v4-pro", "openai/deepseek-v4-pro")
    assert mk["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in mk


# ── low / medium / high：按家族注入对应强度 ───────────────────────────

def test_claude_levels_map_to_budget_tokens():
    for level, budget in (("low", 2000), ("medium", 8000), ("high", 16000)):
        mk = _compute(level, "anthropic", "claude-opus-4-8", "anthropic/claude-opus-4-8")
        assert mk["thinking"] == {"type": "enabled", "budget_tokens": budget}
        assert mk["extra_body"] == {"stream": True}


def test_claude_proxy_high_enabled_budget():
    mk = _compute("high", "custom", "claude-sonnet-4-6", "claude-sonnet-4-6")
    assert mk["thinking"] == {"type": "enabled", "budget_tokens": 16000}


def test_gemini_native_levels_map_to_budget():
    for level, budget in (("low", 512), ("medium", 2048), ("high", 8192)):
        mk = _compute(level, "gemini", "gemini-flash-lite", "gemini/gemini-flash-lite")
        assert mk["extra_body"]["generationConfig"]["thinkingConfig"]["thinkingBudget"] == budget


def test_gemini_native_pro_high_budget():
    mk = _compute("high", "gemini", "gemini-3.1-pro-preview", "gemini/gemini-3.1-pro-preview")
    assert mk["extra_body"]["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 8192


def test_native_openai_levels_map_to_reasoning_effort():
    for level, effort in (("low", "low"), ("medium", "medium"), ("high", "high")):
        mk = _compute(level, "openai", "gpt-4o-mini", "openai/gpt-4o-mini")
        assert mk["reasoning_effort"] == effort


def test_doubao_high_enabled_thinking():
    mk = _compute("high", "custom", "doubao-pro", "openai/doubao-pro")
    assert mk["extra_body"] == {"thinking": {"type": "enabled"}}


def test_deepseek_high_enabled_thinking():
    mk = _compute("high", "openai", "deepseek-v4-pro", "openai/deepseek-v4-pro")
    assert mk["extra_body"] == {"thinking": {"type": "enabled"}}


def test_qwen3_high_still_forced_off():
    """Qwen3 系列 reasoning_content 流式与 LangChain 不兼容 → 无论档位强制关。"""
    mk = _compute("high", "aliyun", "qwen3-plus", "openai/qwen3-plus")
    assert mk["extra_body"]["enable_thinking"] is False
    assert mk["extra_body"]["reasoning_effort"] == "low"


def test_unknown_level_treated_as_off():
    mk = _compute("bogus", "openai", "gpt-4o-mini", "openai/gpt-4o-mini")
    assert mk["reasoning_effort"] == "low"
