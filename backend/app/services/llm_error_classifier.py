"""R2-2 · LLM 异常分类纯函数 · 从 stream_service.py 抽出。

输入：任意异常（典型来自 litellm / httpx 传输层）
输出：4 元组 (retriable: bool, code: str, user_message: str, request_id: str | None)

调用方：
- stream_service.stream_chat_reply 用它决定是否重试 + 给用户什么提示
- resilient_llm 子类同样的判定（避免两处发散）
- 任何 LLM 调用 caller 都可复用本分类
"""
from __future__ import annotations

import re

import httpx
import litellm


# 从 Provider 响应体 JSON 中提取 request_id（用于排障）
_REQUEST_ID_RE = re.compile(r'"request_id"\s*:\s*"([^"]+)"')


def classify_llm_error(
    exc: BaseException,
) -> tuple[bool, str, str, str | None]:
    """对 LLM 调用异常分类。

    - retriable:     是否适合重试（瞬时网关/限流/连接类错误）
    - code:          机器可读错误码
    - user_message:  面向用户的简洁提示文案（不含原始异常细节）
    - request_id:    从下游 Provider 响应中提取的 request_id（可为 None）
    """
    exc_str = str(exc)
    request_id: str | None = None
    m = _REQUEST_ID_RE.search(exc_str)
    if m:
        request_id = m.group(1)

    # ── 可重试：瞬时网关 / 限流 / 网络连接问题（用 getattr 防 litellm 版本差异）──
    def _is_litellm(cls_name: str) -> bool:
        cls = getattr(litellm, cls_name, None)
        return cls is not None and isinstance(exc, cls)

    if _is_litellm("BadGatewayError"):
        return True, "BAD_GATEWAY", "上游服务网关异常（502），正在自动重试…", request_id
    if _is_litellm("ServiceUnavailableError"):
        return True, "SERVICE_UNAVAILABLE", "上游服务暂时不可用（503），正在自动重试…", request_id
    if _is_litellm("GatewayTimeoutError"):
        return True, "GATEWAY_TIMEOUT", "上游服务响应超时（504），正在自动重试…", request_id
    if _is_litellm("RateLimitError"):
        return True, "RATE_LIMIT", "请求频率超限（429），等待后将自动重试…", request_id
    if _is_litellm("InternalServerError"):
        return True, "INTERNAL_SERVER_ERROR", "上游服务内部错误（500），正在自动重试…", request_id
    if "500" in exc_str and ("internal" in exc_str.lower() or "status" in exc_str.lower()):
        return True, "INTERNAL_SERVER_ERROR", "上游服务内部错误（500），正在自动重试…", request_id

    if isinstance(exc, (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError)):
        return True, "CONNECTION_ERROR", "网络连接失败，正在自动重试…", request_id
    if isinstance(exc, httpx.TimeoutException):
        return True, "TIMEOUT", "网络请求超时，正在自动重试…", request_id

    # ── 不可重试：鉴权、参数错误、模型不存在等硬失败 ──
    if _is_litellm("AuthenticationError"):
        return False, "AUTH_ERROR", "API Key 无效或无权限，请联系管理员检查 Provider 配置", request_id
    if _is_litellm("NotFoundError") or _is_litellm("BadRequestError"):
        return False, "BAD_REQUEST", "请求参数有误或模型不存在，请联系管理员检查配置", request_id
    if _is_litellm("ContextWindowExceededError"):
        return False, "CONTEXT_WINDOW", "上下文超长，请在新的会话分支中继续", request_id

    # 兜底：未知错误，保守不重试
    return False, "LLM_ERROR", "AI 服务出现意外错误，请稍后重试", request_id
