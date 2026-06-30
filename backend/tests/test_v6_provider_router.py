"""R3-3 · provider_router 纯函数 · 从 agent_service._build_llm 抽 LiteLLM 路由 switch。

route 决定走哪条 SDK 路径；should_stream 决定是否降级非流式。都是纯 switch，
之前埋在 100-LOC _build_llm 里没法独立测「custom+gemini 应关流」这类矩阵。
"""
from __future__ import annotations

import pytest


# ── resolve_route ──
def test_route_anthropic_native():
    from app.domain.llm.provider_router import resolve_route
    assert resolve_route("anthropic", "claude-opus-4-6") == "anthropic/claude-opus-4-6"


def test_route_custom_claude_keeps_bare_model_id():
    """custom + claude-* → 裸 model_id 走 LiteLLM Anthropic 路径（支持 api_base 覆盖）。"""
    from app.domain.llm.provider_router import resolve_route
    assert resolve_route("custom", "claude-opus-4-6") == "claude-opus-4-6"


def test_route_custom_gemini_forces_openai_prefix():
    """custom + gemini-* → 强制 openai/ 前缀（否则 LiteLLM 走 Vertex AI 失败）。"""
    from app.domain.llm.provider_router import resolve_route
    assert resolve_route("custom", "gemini-3-pro") == "openai/gemini-3-pro"


def test_route_openai_compat_types():
    from app.domain.llm.provider_router import resolve_route
    assert resolve_route("dashscope", "qwen-max") == "openai/qwen-max"
    assert resolve_route("aliyun", "qwen3") == "openai/qwen3"


def test_route_openai_native():
    from app.domain.llm.provider_router import resolve_route
    assert resolve_route("openai", "gpt-4o") == "openai/gpt-4o"


# ── should_stream ──
def test_should_stream_default_true():
    from app.domain.llm.provider_router import should_stream
    assert should_stream("anthropic", "claude-opus-4-6") is True


def test_should_stream_custom_gemini_false():
    """custom + gemini → 关流（带 tools 时丢 content 的 bug）。"""
    from app.domain.llm.provider_router import should_stream
    assert should_stream("custom", "gemini-3-pro") is False
    assert should_stream("custom", "my-gemini-variant") is False


def test_should_stream_custom_claude_true():
    """custom + claude → 仍开流（靠 extra_body 强制 SSE）。"""
    from app.domain.llm.provider_router import should_stream
    assert should_stream("custom", "claude-opus-4-6") is True
