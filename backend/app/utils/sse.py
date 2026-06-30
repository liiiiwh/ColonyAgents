"""SSE 工具：keepalive 包装器，防止 k8s ingress / nginx / Cloudflare 等中间代理在
SSE 静默期间（如 LLM 长思考、Worker 工具长耗时）按 idle timeout 断开连接。

典型默认 idle timeout：
- nginx ingress: 60s（`proxy-read-timeout`）
- AWS ALB: 60s
- Cloudflare: 100s
- 不少企业网关 / Skywalker 测试环境: 100-120s

SSE 协议规定以 `:` 起始的行是**注释**，客户端 EventSource / fetch reader 都会忽略；
但 TCP 层有数据流过 → 中间代理判活成功，连接保持。每 15s 喷一条 `: keepalive\\n\\n`
足够穿透绝大多数代理。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T", str, bytes)

#: 默认心跳间隔。比常见代理 idle timeout（60-100s）小一档，留足往返余量。
SSE_KEEPALIVE_INTERVAL_SEC: float = 15.0
SSE_KEEPALIVE_LINE: str = ": keepalive\n\n"


async def keepalive(
    source: AsyncIterator[T],
    *,
    interval: float = SSE_KEEPALIVE_INTERVAL_SEC,
    ping: str = SSE_KEEPALIVE_LINE,
) -> AsyncIterator[T]:
    """把任意 SSE 字符串异步迭代器包成"静默时自动喷心跳"的版本。

    用法：`StreamingResponse(keepalive(_my_sse_gen()), ...)`

    实现：开一个生产者 task 把 source 排空到 queue；主 generator 从 queue 取数据，
    `wait_for(interval)` 超时则 yield 心跳。生产者结束（StopIteration / 异常）
    放哨兵让主 generator 退出。

    注意：心跳作为 str / bytes 直接 yield，与 source 元素**类型**保持一致；
    bytes 流场景调用方需自行 `ping=b": keepalive\\r\\n\\r\\n"`。
    """
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()
    error_holder: list[BaseException] = []

    async def _drain() -> None:
        try:
            async for item in source:
                await queue.put(item)
        except BaseException as exc:  # noqa: BLE001 — 透传上游异常，主流程会重抛
            error_holder.append(exc)
        finally:
            await queue.put(sentinel)

    drain_task = asyncio.create_task(_drain())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield ping  # type: ignore[misc]
                continue
            if item is sentinel:
                if error_holder:
                    raise error_holder[0]
                return
            yield item
    finally:
        if not drain_task.done():
            drain_task.cancel()
            try:
                await drain_task
            except (asyncio.CancelledError, Exception):
                pass
