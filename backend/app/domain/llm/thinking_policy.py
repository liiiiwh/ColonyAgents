"""thinking_policy 纯函数 · per-family 思考档位（thinking_level）映射。

compute_thinking_model_kwargs：把抽象档位 off/low/medium/high 按主模型真实家族
（claude / gemini / doubao / qwen3 / deepseek / o-series 等）映射成各家具体参数。
默认 off（最省 token / 最快首 token）。

档位 → 强度：
  - gemini:   thinkingBudget = 0 / 512 / 2048 / 8192（Pro 系下限 128）
  - claude:   thinking.budget_tokens = disabled / 2000 / 8000 / 16000
  - 其它:     reasoning_effort = low / low / medium / high
              （reasoning_effort 合法值 minimal/low/medium/high；off 仍给 low，
               o-series 等无法真正关思考）

★ R4-2 修复 R3 flagged bug：
  - native openai（provider_type='openai'）→ 顶层 reasoning_effort（真 OpenAI SDK 接受）
  - openai-compat 代理（custom/dashscope/volcengine/aliyun，route 走 openai/）→ extra_body 透传
    （LiteLLM 严格校验 OpenAI schema，顶层 reasoning_effort 会 UnsupportedParamsError）

★ DeepSeek 专项：thinking_mode 用 extra_body={"thinking":{"type": enabled|disabled}} 控制
  （官方文档；reasoning_effort 对 DeepSeek 无效），无 budget 概念。

★ Qwen3 系列（DashScope openai-compat）：thinking ON 时所有输出走 reasoning_content
  字段、content=None，当前 LiteLLM/LangChain 链路不识别 → SILENT_END_NO_FINAL_TEXT。
  **无论档位一律强制关**，直到底层适配能透出 reasoning_content。

纯函数，矩阵可独立测（test_v6_thinking_policy.py）。详见 agent_service._build_llm 原注释。
"""
from __future__ import annotations

from typing import Any

from app.domain.llm.provider_router import _OPENAI_COMPAT_TYPES

_VALID_LEVELS = ("off", "low", "medium", "high")

# 档位 → 各家族具体强度
_GEMINI_BUDGET = {"off": 0, "low": 512, "medium": 2048, "high": 8192}
_CLAUDE_BUDGET = {"low": 2000, "medium": 8000, "high": 16000}
# reasoning_effort 合法值 minimal/low/medium/high；off 仍给 low（o-series 等无法真正关）。
_REASONING_EFFORT = {"off": "low", "low": "low", "medium": "medium", "high": "high"}


def compute_thinking_model_kwargs(
    *,
    level: str,
    provider_type: str,
    model_id: str,
    route: str,
) -> dict[str, Any]:
    """档位 → 关闭/限制 thinking 的 model_kwargs。未知档位按 off 处理。"""
    lvl = (level or "").lower()
    if lvl not in _VALID_LEVELS:
        lvl = "off"
    thinking_on = lvl != "off"

    mid_lower = (model_id or "").lower()
    is_claude = mid_lower.startswith("claude")
    is_gemini = mid_lower.startswith("gemini") or "gemini" in mid_lower
    is_gemini_pro = is_gemini and "pro" in mid_lower
    is_doubao = mid_lower.startswith("doubao") or "doubao" in mid_lower
    is_qwen3 = (
        mid_lower.startswith("qwen3")
        or mid_lower.startswith("qwen-plus")
        or "qwen3" in mid_lower
    )
    is_deepseek = "deepseek" in mid_lower

    model_kwargs: dict[str, Any] = {}

    if provider_type == "anthropic" or is_claude:
        # Claude 原生 / Nebula 代理 Claude：thinking 必须**显式**双向注入（OFF/ON 都主动设，
        # 否则 UI 上调静默失效）。ON 时 budget_tokens 按档位取；恒附 stream（不混 reasoning_effort，否则 502）。
        if thinking_on:
            model_kwargs["thinking"] = {"type": "enabled", "budget_tokens": _CLAUDE_BUDGET[lvl]}
        else:
            model_kwargs["thinking"] = {"type": "disabled"}
        model_kwargs["extra_body"] = {"stream": True}
    elif provider_type == "gemini":
        # Google 原生：generationConfig.thinkingConfig.thinkingBudget 真正生效。
        # 档位 off/low/medium/high = 0/512/2048/8192；Pro 强制 thinking、budget=0 会 400 → 下限 128。
        budget = _GEMINI_BUDGET[lvl]
        if is_gemini_pro:
            budget = max(128, budget)
        model_kwargs["extra_body"] = {
            "generationConfig": {"thinkingConfig": {"thinkingBudget": budget}}
        }
    elif is_gemini:
        # 代理 Gemini（openai/ 路由）：reasoning_effort 进 extra_body + 附 thinkingConfig 兜底
        budget = _GEMINI_BUDGET[lvl]
        if is_gemini_pro:
            budget = max(128, budget)
        model_kwargs["extra_body"] = {
            "reasoning_effort": _REASONING_EFFORT[lvl],
            "generationConfig": {"thinkingConfig": {"thinkingBudget": budget}},
        }
    elif is_deepseek:
        # DeepSeek V4：thinking_mode 唯一控制法是 extra_body={"thinking":{"type": enabled|disabled}}
        #（官方 thinking_mode 文档；reasoning_effort 对 DeepSeek 无效）。无 budget 概念。
        model_kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if thinking_on else "disabled"}
        }
    else:
        # 兜底：qwen / doubao / o-series / native-openai / ollama / azure
        #   ① openai-compat 代理（custom/dashscope/volcengine/aliyun，route openai/）→ extra_body
        #   ② native openai（provider_type='openai'）→ 顶层 reasoning_effort（真 OpenAI 接受）
        #   ③ 原生 SDK 路径（azure/ollama，route 非 openai/）→ 顶层 reasoning_effort
        is_proxy_openai_route = (
            route.startswith("openai/") and provider_type in _OPENAI_COMPAT_TYPES
        )
        if is_proxy_openai_route:
            if is_doubao:
                model_kwargs["extra_body"] = {
                    "thinking": {"type": "enabled" if thinking_on else "disabled"}
                }
            else:
                extra: dict[str, Any] = {"reasoning_effort": _REASONING_EFFORT[lvl]}
                # Qwen3：reasoning_content 流式与 LangChain 不兼容 → 一律强制关。
                if is_qwen3:
                    extra["reasoning_effort"] = "low"
                    extra["enable_thinking"] = False
                model_kwargs["extra_body"] = extra
        else:
            # native openai / azure / ollama → 顶层 reasoning_effort
            model_kwargs["reasoning_effort"] = _REASONING_EFFORT[lvl]

    return model_kwargs
