"""worker LLM token 用量汇总（纯函数）。

病根：`worker_invocation_log.tokens_in/out` 一直为空——`__finalize_log` 只写
status/duration/artifact，从不写 token，于是 worker 观察页「token 消耗」恒为 0。

解法：worker 跑完后 `result["messages"]` 里每条 AIMessage 带用量元数据；本函数把整条
对话（一次 invoke 可能多轮 tool-call）的用量加总。兼容两种 provider 形态：
  - langchain 原生 `usage_metadata`: {input_tokens, output_tokens}
  - OpenAI 风格 `response_metadata.token_usage`: {prompt_tokens, completion_tokens}
取到一种即可，避免重复计数（优先 usage_metadata）。
"""
from __future__ import annotations


def _msg_usage(m) -> tuple[int, int]:
    """单条消息的 (in, out)。非 AIMessage / 无用量 → (0,0)。"""
    um = getattr(m, "usage_metadata", None)
    if isinstance(um, dict):
        ti = um.get("input_tokens") or um.get("prompt_tokens") or 0
        to = um.get("output_tokens") or um.get("completion_tokens") or 0
        if ti or to:
            return int(ti), int(to)
    rm = getattr(m, "response_metadata", None)
    if isinstance(rm, dict):
        tu = rm.get("token_usage") or rm.get("usage") or {}
        if isinstance(tu, dict):
            ti = tu.get("prompt_tokens") or tu.get("input_tokens") or 0
            to = tu.get("completion_tokens") or tu.get("output_tokens") or 0
            if ti or to:
                return int(ti), int(to)
    return 0, 0


def sum_message_usage(msgs) -> tuple[int, int]:
    """汇总一次 worker invoke 全部消息的 (tokens_in, tokens_out)。"""
    if not msgs:
        return 0, 0
    ti = to = 0
    for m in msgs:
        a, b = _msg_usage(m)
        ti += a
        to += b
    return ti, to
