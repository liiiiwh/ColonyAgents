"""带"首 token 预算 + 可重试异常"自动重试的 ChatLiteLLM 子类。

背景：
- Nebula 等 OpenAI-compat 代理偶发 502 / 503 / 504 / gateway timeout；直接把失败抛给用户
  体验很糟
- Claude / Gemini 有时首 token 会卡在 20+ 秒（thinking token 不流出；或上游排队）
- Agent 自身的 ReAct loop 已尽量关闭 thinking（见 _build_llm 里的 provider 分支）；
  但仍然可能遇到上述问题

本模块提供 `ResilientChatLiteLLM`：
- 首 token 预算 `first_token_timeout_s` 秒（默认 3s）。超过则取消上游流、重试
- 可重试异常：响应体里包含 502 / 503 / 504 / "bad gateway" / "timeout" / "connection reset"
  字样的异常；通过 `_is_retryable` 判断
- 最多 `max_retries` 次（默认 3）。耗尽后抛最后一次异常
- **一旦已 yield 过至少一个 chunk 给下游，停止重试**（避免把已回显给用户的内容重放）

使用：`_build_llm` 里把 `ChatLiteLLM(**kwargs)` 换成 `ResilientChatLiteLLM(**kwargs)` 即可。
所有 LangChain / LangGraph 的下游行为不变（`.bind_tools()`、`astream_events` 等
都是 BaseChatModel 的默认实现，会回调到我们重写的 `_astream`）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
import litellm
from langchain_litellm import ChatLiteLLM

from app.core.config import settings

logger = logging.getLogger(__name__)

# 代码层修复 · 平台按 thinking_policy 注入 reasoning_effort/thinking 等关思考参数，但部分模型
# （如 openai-compat 代理的 qwen3.6-plus）不认 → litellm 抛 UnsupportedParamsError、worker tick 崩。
# drop_params=True 让 litellm 按各模型能力**静默丢弃**不支持的参数，而非报错（最坏只是该模型
# 不关思考，不崩）。这类是平台框架层问题，Builder Agent 改 agent 配置够不到，必须在此修。
litellm.drop_params = True

#: 单次 LLM 调用命中 length 上限时，最多续写多少轮（不含首轮）。
#: 3 次续写意味着最坏情况单个逻辑响应由 4 段拼成 ≤ 4 × max_tokens，足够应对 5000 tok 以内的
#: 常规 Markdown 交付物。继续往大开不现实——段数越多拼接越容易漂移。
MAX_CONTINUATIONS = 3

#: 续写提示。要求模型从中断处接续，不重复、不解释。
_CONTINUE_PROMPT = """你上一次输出已达到单次输出 token 上限，请**从中断处紧接着继续**，直到正文自然结束。
约束：
- 不要重复已经输出过的内容；
- 不要说『继续』/『接上文』/『以下是续写』等任何元说明；
- 直接接着写，保持原格式（Markdown / JSON / 其它）。
如果上一次本来就已经写完，只是少了结束符，也请补齐结束符后直接停止。"""


#: 异常字符串里出现任一 marker 即视为可重试
RETRYABLE_MARKERS: tuple[str, ...] = (
    "500",
    "502",
    "503",
    "504",
    "internal server error",
    "internal_server_error",
    "internalservererror",
    "bad gateway",
    "badgateway",
    "service unavailable",
    "gateway timeout",
    "apitimeouterror",
    "apiconnectionerror",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "remotedisconnected",
    "incompleteread",
)


def _is_retryable_exc(exc: BaseException) -> bool:
    """判断异常是否属于网络/上游临时故障，可以安全重试。"""
    s = f"{type(exc).__name__} {exc}".lower()
    return any(m in s for m in RETRYABLE_MARKERS)


#: 不同 provider 对"长度截断"的命名不同；只要命中任一，就视为 length-stop
_LENGTH_STOP_TOKENS: frozenset[str] = frozenset(
    {"length", "max_tokens", "max_output_tokens", "max_tokens_exceeded"}
)


def _extract_finish_reason(chunk: ChatGenerationChunk) -> str | None:
    """从一个 chunk 里取 finish_reason（跨 provider 兼容）。

    finish_reason 可能出现的位置：
    - `chunk.generation_info["finish_reason"]`（LangChain 标准）
    - `chunk.message.response_metadata["finish_reason"]`（OpenAI-style）
    - `chunk.message.response_metadata["stop_reason"]`（**Anthropic 原生**：`"max_tokens"`/
      `"end_turn"`/`"tool_use"`/`"stop_sequence"`）
    - `chunk.message.additional_kwargs["finish_reason"]` 或 `["stop_reason"]`

    不同 provider 对命中 max_tokens 的 token 不同（OpenAI=`"length"`，Anthropic=`"max_tokens"`）。
    上层用 `_is_length_stop(fr)` 做归一判定。
    """
    # 1. generation_info
    gi = getattr(chunk, "generation_info", None) or {}
    if isinstance(gi, dict):
        for key in ("finish_reason", "stop_reason"):
            fr = gi.get(key)
            if fr:
                return str(fr)
    # 2. message.response_metadata
    msg = getattr(chunk, "message", None)
    if msg is not None:
        rm = getattr(msg, "response_metadata", None) or {}
        if isinstance(rm, dict):
            for key in ("finish_reason", "stop_reason"):
                fr = rm.get(key)
                if fr:
                    return str(fr)
        # 3. message.additional_kwargs
        ak = getattr(msg, "additional_kwargs", None) or {}
        if isinstance(ak, dict):
            for key in ("finish_reason", "stop_reason"):
                fr = ak.get(key)
                if fr:
                    return str(fr)
    return None


def _is_length_stop(finish_reason: str | None) -> bool:
    """判断 finish_reason 是否是"长度上限触发的截断"。跨 provider 归一。"""
    if not finish_reason:
        return False
    return finish_reason.lower() in _LENGTH_STOP_TOKENS


def _chunk_usage_hit_limit(chunk: ChatGenerationChunk, max_tokens: int | None) -> bool:
    """Fallback 检测：`usage_metadata.output_tokens >= max_tokens` 也视为命中 length 上限。

    兜底场景：某些 provider 的 streaming chunk 不带 finish_reason / stop_reason，
    只能靠 usage.output_tokens 反推。不完全准（模型可能刚好卡在上限），但比漏检好。
    """
    if not max_tokens:
        return False
    msg = getattr(chunk, "message", None)
    if msg is None:
        return False
    um = getattr(msg, "usage_metadata", None)
    if not isinstance(um, dict):
        # 某些实现通过 response_metadata.usage
        rm = getattr(msg, "response_metadata", None) or {}
        um = rm.get("usage") if isinstance(rm, dict) else None
    if not isinstance(um, dict):
        return False
    out_tokens = um.get("output_tokens") or um.get("completion_tokens")
    try:
        return int(out_tokens or 0) >= int(max_tokens)
    except (TypeError, ValueError):
        return False


def _chunk_has_tool_call(chunk: ChatGenerationChunk) -> bool:
    """判断本 chunk 是否涉及 tool_call（任意 tool_call 片段）。

    LangChain 的 AIMessageChunk 会把 streaming 的 tool_call JSON 参数按片段放在
    `tool_call_chunks`（每段含 index/name/args 的片段）或最终落到 `tool_calls`。
    """
    msg = getattr(chunk, "message", None)
    if msg is None:
        return False
    tcc = getattr(msg, "tool_call_chunks", None)
    if tcc:
        return True
    tc = getattr(msg, "tool_calls", None)
    if tc:
        return True
    # OpenAI/litellm 有时把 function_call 放到 additional_kwargs
    ak = getattr(msg, "additional_kwargs", None) or {}
    if isinstance(ak, dict) and (ak.get("tool_calls") or ak.get("function_call")):
        return True
    return False


def _chunk_text(chunk: ChatGenerationChunk) -> str:
    """抽取 chunk 的纯文本部分。content 可能是 str / list[dict] / None。"""
    msg = getattr(chunk, "message", None)
    if msg is None:
        return ""
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
        return "".join(parts)
    return ""


#: 模型回吐、但严格模型（qwen3.6-plus 等）不接受回填的 content 块类型 —— 重放历史前剔除。
_DROP_CONTENT_TYPES = {"thinking", "reasoning", "redacted_thinking", "reasoning_content"}


def _sanitize_message_content(content: Any) -> Any:
    """把 message content（可能是 list[dict]）收敛成严格模型可接受的形式。

    背景：qwen3.6-plus 等会把推理过程作为 `[{"type":"thinking",...}]` 放进 assistant content；
    agent 多轮循环把这条 assistant 消息回填时，qwen 报 `Unexpected item type in content`。
    这里剔除 thinking/reasoning 块；剩余全是 text 就收敛成纯字符串（qwen 对 list 形式也挑剔），
    含 image_url 等多模态则保留 list。
    """
    if not isinstance(content, list):
        return content
    kept: list[Any] = []
    for part in content:
        if isinstance(part, str):
            kept.append({"type": "text", "text": part})
        elif isinstance(part, dict):
            if part.get("type") in _DROP_CONTENT_TYPES:
                continue
            kept.append(part)
    if not kept:
        return ""
    if all(isinstance(p, dict) and p.get("type") == "text" for p in kept):
        return "".join(str(p.get("text") or "") for p in kept)
    return kept


def _sanitize_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """重放历史前，逐条把 list-content 里的 thinking/reasoning 块剔除（不改原对象）。"""
    out: list[BaseMessage] = []
    for m in messages:
        c = getattr(m, "content", None)
        if isinstance(c, list):
            new_c = _sanitize_message_content(c)
            if new_c != c:
                try:
                    m = m.model_copy(update={"content": new_c})
                except Exception:  # noqa: BLE001 — 兜底：拷不动就原样
                    pass
        out.append(m)
    return out


class ResilientChatLiteLLM(ChatLiteLLM):
    """在 ChatLiteLLM 之上加一层"首 token 预算 + 可重试异常"自动重试。

    默认值从 `settings.LLM_RETRY_MAX` / `settings.LLM_FIRST_TOKEN_TIMEOUT_S` 读取，
    对应 .env 的 `LLM_RETRY_MAX` / `LLM_FIRST_TOKEN_TIMEOUT_S` 两个变量。
    调用方可在构造时显式传参覆盖（主要便于单元测试）。
    """

    #: 最多重试次数（不含初始那次）。0 = 禁用重试；与 settings.LLM_RETRY_MAX 同步
    max_retries: int = settings.LLM_RETRY_MAX
    #: 首 token 预算秒数；与 settings.LLM_FIRST_TOKEN_TIMEOUT_S 同步
    first_token_timeout_s: float = settings.LLM_FIRST_TOKEN_TIMEOUT_S

    # 让 pydantic / BaseChatModel 识别这两个可配置字段
    class Config:  # type: ignore[no-redef]
        arbitrary_types_allowed = True

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """外层：length-stop 自动续写。

        做法：把 `_astream_once` 产出的 chunk 边收边 yield，同时嗅探最后一条 chunk 的
        `generation_info.finish_reason`。
        - `stop` / `tool_calls` / 其它正常结束 → 直接把末 chunk 也 yield 出去，return
        - `length` 且本段**没有 tool_call**  → 丢弃末 chunk 的 finish_reason（不让下游
          判定"生成结束"），按累积文本 + 续写提示构造下一段 messages，再跑 `_astream_once`，
          继续向下游拼接。上限 MAX_CONTINUATIONS（默认 3）段。
        - `length` 但当前段已含 tool_call → 抛错：tool_call 参数被截成半句 JSON 无法安全续接，
          让上层 Agent（或 Agent 协议）负责分块写

        这样拼出的对外视图：一个完整的 AIMessage（chunks 连续 yield，末 chunk 的
        finish_reason 是最后一段的 finish_reason），下游 LangGraph Agent 感知不到分段。
        """
        # 当前调用的 max_tokens 阈值，用于 usage fallback 检测
        effective_max_tokens: int | None = (
            kwargs.get("max_tokens") or getattr(self, "max_tokens", None)
        )
        # 重放历史前剔除 thinking/reasoning content 块（qwen 等会拒绝回填自己的 thinking）
        current_messages: list[BaseMessage] = _sanitize_messages(list(messages))
        for continuation in range(MAX_CONTINUATIONS + 1):
            # 缓存当前段累积的"纯文本内容"（用于续写时把已输出内容回塞给模型）
            # 以及是否检测到 tool_call（决定 length 时能否续写）
            segment_text_parts: list[str] = []
            segment_has_tool_call = False
            # pending_chunk：finish_reason 所在那条末 chunk，暂不 yield
            # —— 如果是 length-stop 且要续写 / 要抛错，都不应该把这条 yield 出去
            # （否则下游 LangGraph 会把它当成一次完整"结束"事件）
            pending_final_chunk: ChatGenerationChunk | None = None
            final_finish_reason: str | None = None
            length_stop_detected = False  # 优先看 finish_reason；fallback 看 usage

            async for chunk in self._astream_once(
                current_messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                # 是否含 tool_call（累积判断，任一 chunk 出现即标记）
                if _chunk_has_tool_call(chunk):
                    segment_has_tool_call = True
                # 累积文本（只统计 str 类型 content；content 可能是 None 或 list）
                txt = _chunk_text(chunk)
                if txt:
                    segment_text_parts.append(txt)
                # 探测 finish_reason
                fr = _extract_finish_reason(chunk)
                # Fallback：chunk 不带 finish_reason 但 usage.output_tokens 已达上限
                usage_hit = _chunk_usage_hit_limit(chunk, effective_max_tokens)

                if fr is not None or usage_hit:
                    # 本 chunk 是"末 chunk"候选。是否视为 length-stop?
                    if _is_length_stop(fr) or usage_hit:
                        length_stop_detected = True
                    final_finish_reason = fr
                    pending_final_chunk = chunk
                    # **不** yield —— 要么等续写把整段补完（length），
                    # 要么等 raise（length + tool_call），
                    # 要么在循环出口作为"正常末 chunk"再 yield
                    continue
                # 非末 chunk，正常透传
                yield chunk

            # ── 本段结束，决策 ──
            if not length_stop_detected:
                # 正常结束 —— 把缓存的末 chunk 如实 yield 出去
                if pending_final_chunk is not None:
                    yield pending_final_chunk
                return

            # 命中 length 上限
            if segment_has_tool_call:
                # tool_call JSON 参数大概率被截成半句 → 即便 LangChain 的 json_repair
                # "修好"了 JSON 也很可能丢失 content 字段，让 Agent 误用空参数调工具。
                # 不 yield 末 chunk（否则 LangGraph 会用残缺的 tool_call 真的去执行）。
                # 抛错让 Agent/上层感知并自我修正。
                logger.warning(
                    "❌ LLM length-stop 时包含 tool_call（可能 content 参数被截）；"
                    "fr=%s max_tokens=%s；不 yield 末 chunk，抛错让上层分块调用",
                    final_finish_reason,
                    effective_max_tokens,
                )
                raise RuntimeError(
                    f"LLM output hit max_tokens ({effective_max_tokens}) mid tool_call "
                    f"(finish_reason={final_finish_reason!r}). Tool arguments were likely "
                    "truncated — split your arguments into multiple shorter tool calls, "
                    "or raise the agent's max_output_tokens."
                )

            if continuation >= MAX_CONTINUATIONS:
                # 续写次数耗尽：把末 chunk 还是 yield 出去（忠实反映上游已 "length" 终止）
                if pending_final_chunk is not None:
                    yield pending_final_chunk
                logger.warning(
                    "⚠️ LLM 续写达上限 %d，仍未自然结束；生成可能不完整",
                    MAX_CONTINUATIONS,
                )
                return

            # 纯文本 length-stop → 继续下一段
            produced_text = "".join(segment_text_parts)
            logger.info(
                "✂️ LLM length-stop 触发自动续写 (continuation %d/%d)：fr=%s 已产出 %d 字符",
                continuation + 1,
                MAX_CONTINUATIONS,
                final_finish_reason,
                len(produced_text),
            )
            current_messages = list(current_messages) + [
                AIMessage(content=produced_text),
                HumanMessage(content=_CONTINUE_PROMPT),
            ]
            # 下一段 max_tokens 继续使用原 kwargs/构造时的配置，无需修改

    async def _astream_once(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """内层：首 token 预算 + 可重试异常重试。"""
        last_exc: BaseException | None = None
        total_attempts = self.max_retries + 1  # 初始 1 次 + 最多 max_retries 次重试

        for attempt in range(1, total_attempts + 1):
            inner: AsyncIterator[ChatGenerationChunk] | None = None
            first_chunk: ChatGenerationChunk | None = None
            try:
                inner = super()._astream(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )

                # ── 首 token 预算 ──
                try:
                    first_chunk = await asyncio.wait_for(
                        inner.__anext__(), timeout=self.first_token_timeout_s
                    )
                except asyncio.TimeoutError:
                    last_exc = TimeoutError(
                        f"First token budget exceeded "
                        f"({self.first_token_timeout_s}s) on attempt {attempt}"
                    )
                    logger.warning(
                        "🔁 LLM TTFT 超时 (attempt %d/%d): %.1fs 内未收到首 token；重试",
                        attempt,
                        total_attempts,
                        self.first_token_timeout_s,
                    )
                    # 关掉上游流；某些实现下 inner 没有 aclose，用 try/except 吞掉
                    try:
                        await inner.aclose()  # type: ignore[union-attr]
                    except Exception:  # noqa: BLE001
                        pass
                    if attempt < total_attempts:
                        continue
                    break  # 耗尽次数，下面统一抛
                except StopAsyncIteration:
                    # 上游一次性返回空流 —— 不是错误，直接结束
                    return

                # ── 首 token 已到，yield 之；之后不再重试（避免重放）──
                yield first_chunk
                async for chunk in inner:
                    yield chunk
                return  # 成功

            except Exception as e:
                # 成功 yield 过首 token 则不重试 —— 但此分支由上方已 return 抵达，
                # 所以这里异常一定发生在"首 token 就绪前"或"首 token 就绪后的 inner 迭代中"。
                # 如果是后者，first_chunk 已被 yield（下游已见），为了避免重放，直接 raise。
                if first_chunk is not None:
                    raise
                if not _is_retryable_exc(e):
                    raise
                last_exc = e
                logger.warning(
                    "🔁 LLM 可重试异常 (attempt %d/%d): %s: %s；重试",
                    attempt,
                    total_attempts,
                    type(e).__name__,
                    str(e)[:200],
                )
                if attempt >= total_attempts:
                    break
                # 非首 token 已 yield，可以安全重试
                continue

        # 耗尽重试
        assert last_exc is not None, "retry loop exited without capturing exception"
        logger.error(
            "❌ LLM 重试耗尽（共尝试 %d 次）：%s", total_attempts, last_exc
        )
        raise last_exc

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """非流式路径的重试。

        create_agent 默认走 streaming，本方法罕少走到；但为完整性起见也做一层
        可重试异常重试（无 TTFT 概念，超时依赖底层 httpx）。
        """
        messages = _sanitize_messages(messages)  # 同 _astream：剔除回填的 thinking 块
        last_exc: BaseException | None = None
        total_attempts = self.max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                return await super()._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )
            except Exception as e:
                if not _is_retryable_exc(e):
                    raise
                last_exc = e
                logger.warning(
                    "🔁 LLM _agenerate 可重试异常 (attempt %d/%d): %s",
                    attempt,
                    total_attempts,
                    e,
                )
                if attempt >= total_attempts:
                    break
                continue
        assert last_exc is not None
        raise last_exc
