"""R3-3 · LiteLLM 路由纯函数 · 从 agent_service._build_llm 抽出。

resolve_route：provider_type + model_id → LiteLLM model 路由字符串（决定走哪条 SDK 路径）
should_stream：是否启用 streaming（custom+gemini 带 tools 丢 content → 强制非流式）

纯 switch，无 DB / 网络，矩阵可独立测。详见 _build_llm 原注释。
"""
from __future__ import annotations

# OpenAI-compat 代理类 provider：统一走 openai/ 前缀打到 provider.base_url
_OPENAI_COMPAT_TYPES = {"custom", "dashscope", "volcengine", "aliyun"}


def resolve_route(provider_type: str, model_id: str) -> str:
    """决定 LiteLLM 的 model 路由字符串。

    - custom + claude-*  → 裸 model_id（LiteLLM Anthropic 路径，支持 api_base 覆盖）
    - custom + 其它      → openai/<model_id>（强制 OpenAI-compat HTTP，避免 Vertex AI 误判）
    - dashscope/volcengine/aliyun → openai/<model_id>
    - 其它（anthropic/openai/gemini 等原生）→ <type>/<model_id>
    """
    mid = model_id or ""
    if provider_type == "custom":
        if mid.lower().startswith("claude"):
            return mid
        return f"openai/{mid}"
    if provider_type in _OPENAI_COMPAT_TYPES:
        return f"openai/{mid}"
    return f"{provider_type}/{mid}"


def should_stream(provider_type: str, model_id: str) -> bool:
    """是否启用 streaming。

    custom provider + gemini 家族：streaming 带 tools 时丢全部 content/tool_calls
    （实测 Nebula+Gemini），强制降级非流式。其它默认开。
    """
    mid = (model_id or "").lower()
    if provider_type == "custom" and ("gemini" in mid):
        return False
    return True
