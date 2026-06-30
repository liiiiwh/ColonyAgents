"""验证 agent_service._build_llm 按 Agent.enable_thinking + provider 注入"最严格关闭思考"参数。

直接构造 Agent / LLMModel / LLMProvider 对象（不入库），把 ChatLiteLLM 替换成一个捕获
kwargs 的假类，观察最终 kwargs。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class _FakeProvider:
    id: uuid.UUID
    provider_type: str
    api_key: str = "encrypted-dummy"
    base_url: str | None = "https://nebula.example/v1"


@dataclass
class _FakeModel:
    id: uuid.UUID
    provider_id: uuid.UUID
    model_id: str


@dataclass
class _FakeAgent:
    enable_thinking: bool = False
    thinking_level: str | None = None  # None → _build_llm 回退看 enable_thinking
    temperature: float = 0.7
    extra_config: dict | None = None


class _FakeLLM:
    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kw):
        _FakeLLM.last_kwargs = kw


class _FakeDB:
    def __init__(self, provider):
        self._p = provider

    async def get(self, model_cls, pid):
        return self._p


async def _call(provider_type: str, enable_thinking: bool, *, model_id: str, monkeypatch):
    """调用 _build_llm 并返回 kwargs。"""
    from app.services import agent_service
    # conftest 的 autouse fixture 把 agent_service._build_llm 换成了一个 _FakeLLM 工厂；
    # 本文件专测 _build_llm 的 model_kwargs 注入，需恢复真实现（保存在 ORIGINAL_BUILD_LLM）
    from tests.conftest import ORIGINAL_BUILD_LLM
    monkeypatch.setattr(agent_service, "_build_llm", ORIGINAL_BUILD_LLM)

    # _build_llm 里用 `from app.services.resilient_llm import ResilientChatLiteLLM as ChatLiteLLM`
    # patch 到 spy 类以观察 kwargs
    monkeypatch.setattr(
        "app.services.resilient_llm.ResilientChatLiteLLM",
        _FakeLLM,
    )

    # 解密直接返回明文
    from app.core import encryption

    monkeypatch.setattr(encryption, "decrypt", lambda s: "api-key-plain")

    pid = uuid.uuid4()
    provider = _FakeProvider(id=pid, provider_type=provider_type)
    model = _FakeModel(id=uuid.uuid4(), provider_id=pid, model_id=model_id)
    agent = _FakeAgent(enable_thinking=enable_thinking)
    db = _FakeDB(provider)

    _FakeLLM.last_kwargs = {}
    await agent_service._build_llm(db, model, agent)  # type: ignore[arg-type]
    return _FakeLLM.last_kwargs


def _mk(kw: dict) -> dict:
    """提取 ChatLiteLLM.model_kwargs —— 非标准字段都必须在这里才会真正发出去。"""
    return kw.get("model_kwargs") or {}


def test_claude_extra_body_forces_stream():
    """Claude 分支必须把 stream=True 写到 extra_body —— 否则 LiteLLM 的 Anthropic 路由
    对 custom provider（如 Nebula）不会在 body 里放 stream，上游返回一次性 JSON。

    R4-2：策略已搬到 thinking_policy 纯函数，改为行为断言（比源码哨兵更稳）。
    """
    from app.domain.llm.thinking_policy import compute_thinking_model_kwargs
    mk = compute_thinking_model_kwargs(
        level="off", provider_type="custom",
        model_id="claude-sonnet-4-6", route="claude-sonnet-4-6",
    )
    assert mk.get("extra_body") == {"stream": True}, "Claude 分支需通过 extra_body 强制 stream=True"
    assert mk.get("thinking") == {"type": "disabled"}


@pytest.mark.asyncio
async def test_anthropic_default_disabled_thinking(monkeypatch):
    kw = await _call("anthropic", False, model_id="claude-opus-4-7", monkeypatch=monkeypatch)
    mk = _mk(kw)
    assert mk.get("thinking") == {"type": "disabled"}, "anthropic 应注入 thinking.type=disabled"
    assert mk.get("extra_body") == {"stream": True}, (
        "Claude 分支需要 extra_body.stream=True 绕过 LiteLLM 不放 stream 到 body 的 bug"
    )
    assert "reasoning_effort" not in mk, "anthropic 分支不应混入 reasoning_effort"
    # 顶层不应有这些 ——ChatLiteLLM 会静默丢弃
    assert "thinking" not in kw
    assert "reasoning_effort" not in kw


@pytest.mark.asyncio
async def test_gemini_flash_default_disabled_thinking(monkeypatch):
    """Gemini Flash / Flash-Lite 直连：thinkingBudget=0（true disable）。"""
    kw = await _call("gemini", False, model_id="gemini-3.1-flash-lite-preview", monkeypatch=monkeypatch)
    mk = _mk(kw)
    assert (
        mk["extra_body"]["generationConfig"]["thinkingConfig"]["thinkingBudget"]
        == 0
    ), "Flash/Flash-Lite 需要 thinkingBudget=0"
    # thinkingLevel="off" 是非法值（400），旧代码误用
    assert "thinkingLevel" not in mk.get("extra_body", {}).get("generationConfig", {}).get("thinkingConfig", {})


@pytest.mark.asyncio
async def test_gemini_pro_uses_minimal_budget(monkeypatch):
    """Gemini Pro 系列：模型强制 thinking，budget=0 会 400；只能给最小 128。"""
    for mid in ("gemini-3.1-pro-preview", "gemini-3-pro-preview"):
        kw = await _call("gemini", False, model_id=mid, monkeypatch=monkeypatch)
        mk = _mk(kw)
        assert (
            mk["extra_body"]["generationConfig"]["thinkingConfig"]["thinkingBudget"]
            == 128
        ), f"{mid} Pro 家族需要最小 budget=128"


@pytest.mark.asyncio
async def test_gemini_via_nebula_openai_compat(monkeypatch):
    """Nebula 等 OpenAI-compat 代理 Gemini（provider_type=custom/openai + model_id=gemini-*）：
    路由走 `openai/<model>` 触发 LiteLLM 严格参数校验，`reasoning_effort` 必须放进
    extra_body 透传；额外带 generationConfig.thinkingConfig 作为 Gemini 原生双保险。
    """
    for ptype in ("custom", "openai"):
        kw = await _call(
            ptype, False, model_id="gemini-3.1-flash-lite-preview", monkeypatch=monkeypatch
        )
        mk = _mk(kw)
        eb = mk.get("extra_body")
        assert isinstance(eb, dict), f"{ptype}: 应通过 extra_body 透传 reasoning_effort"
        assert eb.get("reasoning_effort") == "low"
        # Flash / Flash-Lite → thinkingBudget=0
        assert eb.get("generationConfig", {}).get("thinkingConfig", {}).get(
            "thinkingBudget"
        ) == 0, f"{ptype}: Flash/Flash-Lite 应 thinkingBudget=0"
        assert "reasoning_effort" not in mk, (
            f"{ptype}: 不应在顶层 model_kwargs 放 reasoning_effort（会触发 LiteLLM 参数校验报错）"
        )
        assert "thinking" not in mk, "非 Claude 不应注入 thinking"


@pytest.mark.asyncio
async def test_openai_compat_non_claude_non_gemini_uses_reasoning_effort_low(monkeypatch):
    """OpenAI-compat + 底层既不是 Claude 也不是 Gemini（如 o-series / gpt-5）→ reasoning_effort=low。"""
    kw = await _call("openai", False, model_id="gpt-4o-mini", monkeypatch=monkeypatch)
    mk = _mk(kw)
    assert mk.get("reasoning_effort") == "low"
    assert "thinking" not in mk
    assert "extra_body" not in mk


@pytest.mark.asyncio
async def test_openai_compat_claude_proxy_injects_thinking_only(monkeypatch):
    """Nebula 等 OpenAI-compat 代理 Claude（provider_type=custom/openai + model_id=claude-*）
    必须注入 thinking={"type":"disabled"}，且不得注入 reasoning_effort ——
    实测 Nebula + Claude Sonnet 单独带 reasoning_effort 会让上游 Anthropic 返 502。
    """
    for ptype in ("custom", "openai"):
        for mid in ("claude-sonnet-4-6", "claude-opus-4-7", "Claude-3-haiku"):
            kw = await _call(ptype, False, model_id=mid, monkeypatch=monkeypatch)
            mk = _mk(kw)
            assert mk.get("thinking") == {"type": "disabled"}, (ptype, mid)
            assert mk.get("extra_body") == {"stream": True}, (ptype, mid, "需要 stream 强制")
            assert "reasoning_effort" not in mk, (ptype, mid, "reasoning_effort 会触发 502")


@pytest.mark.asyncio
@pytest.mark.parametrize("ptype", ["deepseek", "custom", "azure", "ollama"])
async def test_other_providers_non_claude_non_gemini_default_disabled_thinking(ptype, monkeypatch):
    """非 Claude、非 Gemini 主模型 + 上述 provider → reasoning_effort=low 兜底。

    custom provider 走 openai/ 路由时 LiteLLM 会严格校验参数，`reasoning_effort` 必须放
    extra_body 透传；其它 provider（deepseek / azure / ollama）走原生 SDK 路径，直接
    顶层 `reasoning_effort` 即可。
    """
    kw = await _call(ptype, False, model_id="some-open-source-model-7b", monkeypatch=monkeypatch)
    mk = _mk(kw)
    if ptype == "custom":
        eb = mk.get("extra_body")
        assert isinstance(eb, dict) and eb.get("reasoning_effort") == "low"
        assert "reasoning_effort" not in mk, "custom provider 下顶层放 reasoning_effort 会触发 LiteLLM 校验错误"
    else:
        assert mk.get("reasoning_effort") == "low"
        assert "extra_body" not in mk
    assert "thinking" not in mk


@pytest.mark.asyncio
async def test_enable_thinking_true_falls_back_to_medium(monkeypatch):
    """旧 enable_thinking=True（无 thinking_level）→ 回退 medium 档，注入中等强度思考参数。"""
    # anthropic medium → budget_tokens=8000
    kw = await _call("anthropic", True, model_id="claude-opus-4-8", monkeypatch=monkeypatch)
    assert _mk(kw)["thinking"] == {"type": "enabled", "budget_tokens": 8000}
    # gemini native medium → thinkingBudget=2048
    kw = await _call("gemini", True, model_id="gemini-flash-lite", monkeypatch=monkeypatch)
    assert _mk(kw)["extra_body"]["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 2048
    # native openai medium → 顶层 reasoning_effort=medium
    kw = await _call("openai", True, model_id="gpt-4o-mini", monkeypatch=monkeypatch)
    assert _mk(kw)["reasoning_effort"] == "medium"


@pytest.mark.asyncio
async def test_agent_extra_config_overrides(monkeypatch):
    """Agent.extra_config 里的条目应以最高优先级覆盖默认注入。"""
    from app.services import agent_service
    from app.core import encryption
    from tests.conftest import ORIGINAL_BUILD_LLM

    monkeypatch.setattr(agent_service, "_build_llm", ORIGINAL_BUILD_LLM)
    monkeypatch.setattr(
        "app.services.resilient_llm.ResilientChatLiteLLM", _FakeLLM
    )
    monkeypatch.setattr(encryption, "decrypt", lambda s: "key")

    pid = uuid.uuid4()
    provider = _FakeProvider(id=pid, provider_type="anthropic")
    model = _FakeModel(id=uuid.uuid4(), provider_id=pid, model_id="claude-opus-4-7")
    agent = _FakeAgent(
        enable_thinking=False,
        extra_config={"thinking": {"type": "enabled", "budget_tokens": 10000}, "max_tokens": 4096},
    )
    db = _FakeDB(provider)

    _FakeLLM.last_kwargs = {}
    await agent_service._build_llm(db, model, agent)  # type: ignore[arg-type]
    kw = _FakeLLM.last_kwargs
    mk = _mk(kw)

    # extra_config 覆盖：从 disabled 变 enabled（在 model_kwargs 里）
    assert mk["thinking"] == {"type": "enabled", "budget_tokens": 10000}
    # max_tokens 属于 ChatLiteLLM 顶层已知字段 → 顶层 kwargs
    assert kw["max_tokens"] == 4096
