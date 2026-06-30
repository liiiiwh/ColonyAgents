"""验证 `ResilientChatLiteLLM` 的首 token 预算 + 可重试异常重试。

构造一个 `_stub_astream` 可控流生成器：按 `plan` 顺序依次触发
"首 token 正常"/"TTFT 超时"/"可重试异常"/"不可重试异常" 四种行为，
直接 patch 父类 `ChatLiteLLM._astream`，观察 `ResilientChatLiteLLM._astream` 的重试决策。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.messages import AIMessageChunk


def _chunk(text: str) -> ChatGenerationChunk:
    return ChatGenerationChunk(message=AIMessageChunk(content=text))


@dataclass
class _Plan:
    """每次 _astream 调用按 attempts 顺序消费一次。

    每个元素：("ok", delays, texts) | ("ttft_timeout",) | ("raise_retryable", msg) |
               ("raise_fatal", msg)
    """

    attempts: list[tuple] = field(default_factory=list)
    call_count: int = 0


async def _stub_astream_factory(plan: _Plan, ttft_budget: float):
    """根据 plan[call_count] 返回一个 async generator。"""

    async def _gen(*args: Any, **kwargs: Any) -> AsyncIterator[ChatGenerationChunk]:
        idx = plan.call_count
        plan.call_count += 1
        if idx >= len(plan.attempts):
            raise RuntimeError(f"Unexpected extra call #{idx + 1}")
        step = plan.attempts[idx]
        kind = step[0]
        if kind == "ok":
            _, first_delay, texts = step
            # 首 chunk 前 sleep first_delay；必须小于 ttft_budget 才算正常
            await asyncio.sleep(first_delay)
            for t in texts:
                yield _chunk(t)
            return
        if kind == "ttft_timeout":
            # 模拟 ResilientChatLiteLLM 的 first_token_timeout_s 之内永不到达
            await asyncio.sleep(ttft_budget * 5)
            yield _chunk("should not be yielded")
            return
        if kind == "raise_retryable":
            _, msg = step
            raise RuntimeError(msg)
        if kind == "raise_fatal":
            _, msg = step
            raise ValueError(msg)
        raise RuntimeError(f"unknown step kind: {kind}")

    return _gen


async def _run(plan: _Plan, *, ttft: float = 0.2, max_retries: int = 3):
    """实例化 ResilientChatLiteLLM，patch 父类 _astream 为 stub，执行并收集 yield。"""
    from app.services.resilient_llm import ResilientChatLiteLLM
    from langchain_litellm import ChatLiteLLM

    # 最小化 ChatLiteLLM 构造（不会真的被调用，因为 _astream 被 patch）
    llm = ResilientChatLiteLLM(
        model="openai/gpt-nonexistent",
        api_key="fake",
        max_retries=max_retries,
        first_token_timeout_s=ttft,
    )

    gen = await _stub_astream_factory(plan, ttft)
    # monkeypatch 父类 _astream（实例方法上）
    ChatLiteLLM._astream = gen  # type: ignore[assignment]

    yielded: list[str] = []
    exc: BaseException | None = None
    try:
        async for ch in llm._astream([HumanMessage(content="hi")]):
            yielded.append(str(ch.message.content))
    except BaseException as e:  # noqa: BLE001
        exc = e

    return yielded, exc, plan.call_count


# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_attempt_succeeds():
    plan = _Plan(attempts=[("ok", 0.01, ["hello ", "world"])])
    out, exc, calls = await _run(plan)
    assert exc is None
    assert out == ["hello ", "world"]
    assert calls == 1


@pytest.mark.asyncio
async def test_ttft_timeout_then_success():
    plan = _Plan(
        attempts=[
            ("ttft_timeout",),
            ("ok", 0.01, ["recovered"]),
        ]
    )
    out, exc, calls = await _run(plan, ttft=0.15)
    assert exc is None
    assert out == ["recovered"]
    assert calls == 2


@pytest.mark.asyncio
async def test_retryable_exception_then_success():
    plan = _Plan(
        attempts=[
            ("raise_retryable", "502 Bad Gateway from upstream"),
            ("ok", 0.01, ["ok-now"]),
        ]
    )
    out, exc, calls = await _run(plan)
    assert exc is None
    assert out == ["ok-now"]
    assert calls == 2


@pytest.mark.asyncio
async def test_non_retryable_raises_immediately():
    plan = _Plan(
        attempts=[
            ("raise_fatal", "400 invalid request"),
            # should never be called
            ("ok", 0.01, ["never"]),
        ]
    )
    out, exc, calls = await _run(plan)
    assert out == []
    assert isinstance(exc, ValueError)
    assert calls == 1


@pytest.mark.asyncio
async def test_exhausts_retries_and_raises_last():
    plan = _Plan(
        attempts=[
            ("raise_retryable", "502 once"),
            ("raise_retryable", "503 twice"),
            ("ttft_timeout",),
            ("raise_retryable", "504 fourth"),  # 这个 = max_retries (3) 次重试中的第 3 次重试
        ]
    )
    out, exc, calls = await _run(plan, ttft=0.05, max_retries=3)
    assert out == []
    assert exc is not None
    # 总共 1 + 3 = 4 次尝试
    assert calls == 4
    # 最后一次是 504
    assert "504" in str(exc)


@pytest.mark.asyncio
async def test_mixed_retry_kinds_counted_together():
    """TTFT 超时 + 502 + 成功（3 次调用，耗 2 次重试预算）。"""
    plan = _Plan(
        attempts=[
            ("ttft_timeout",),
            ("raise_retryable", "502"),
            ("ok", 0.01, ["final"]),
        ]
    )
    out, exc, calls = await _run(plan, ttft=0.1, max_retries=3)
    assert exc is None
    assert out == ["final"]
    assert calls == 3


@pytest.mark.asyncio
async def test_no_retry_after_first_chunk_yielded():
    """首 chunk 已 yield 后，inner 迭代中再抛可重试异常 —— 不应重试，直接 raise。"""

    async def _g(*a, **kw):
        yield _chunk("already-flushed")
        raise RuntimeError("502 mid-stream")

    from app.services.resilient_llm import ResilientChatLiteLLM
    from langchain_litellm import ChatLiteLLM

    llm = ResilientChatLiteLLM(
        model="openai/x", api_key="k", max_retries=3, first_token_timeout_s=1.0
    )
    ChatLiteLLM._astream = _g  # type: ignore[assignment]

    yielded = []
    exc = None
    try:
        async for ch in llm._astream([HumanMessage(content="hi")]):
            yielded.append(str(ch.message.content))
    except Exception as e:  # noqa: BLE001
        exc = e

    assert yielded == ["already-flushed"]
    assert exc is not None and "502" in str(exc)
