"""v5 · 平台实时事件总线（in-process pub/sub keyed by session_id）。

设计目标：把 super_dispatch / pending_approvals / memory ops 的事件**实时**推送到
`/api/super/{slug}/stream` SSE 订阅者，替代当前 2s poll。

为什么不上 Redis / WebSocket / PG NOTIFY：
- 当前 `BuiltinToolContext.event_queue` 已是进程内 asyncio.Queue 模式
- 单 uvicorn 进程模式下，进程内 broadcaster 零依赖、零延迟
- 多进程部署再换 PgNotifyBackend（接口预留 ABC）

API 约定：
- 频道键 = `session_id`（每个 super 有 1 个 daemon session）
- subscribe() 返回 async generator；调用方 await 消费；EOF 时自动 unsubscribe
- publish() fire-and-forget，背压：单订阅者队列满 → 丢弃最早事件 + WARN log
- 关闭：当一个 SSE 断开，subscribe 退出 → channel 引用计数 -1；归零 → del

事件 envelope 约定（参考 stream_service 习惯）：
  { "type": str, "ts": float, **payload }
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

# 单订阅者最大背压队列长度；满了丢最早
_MAX_QUEUE = 256
# ADR-029 · 每 channel 重放缓冲上限 + TTL：订阅者连上时补齐「连接空窗/重连期间」publish 的事件。
# 修 fire-and-forget 丢包（daemon tick 常在前端 EventSource 连上前 publish approval_request →
# 旧实现直接丢 → 审批卡渲染成「已关闭」需手刷）。前端 handler 按 id/request_id 幂等，重放安全。
_REPLAY_MAXLEN = 256
_REPLAY_TTL_SEC = 120.0


class EventBusBackend(ABC):
    @abstractmethod
    async def publish(self, channel: uuid.UUID, evt: dict[str, Any]) -> None:
        ...

    @abstractmethod
    def subscribe(self, channel: uuid.UUID) -> AsyncIterator[dict[str, Any]]:
        ...


class InProcessBus(EventBusBackend):
    """单进程 asyncio 实现。"""

    def __init__(self) -> None:
        self._channels: dict[uuid.UUID, set[asyncio.Queue[dict[str, Any]]]] = {}
        # ADR-029 · 每 channel 重放缓冲（最近事件 ring buffer）
        self._replay: dict[uuid.UUID, deque[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, channel: uuid.UUID, evt: dict[str, Any]) -> None:
        evt.setdefault("ts", time.time())
        async with self._lock:
            # ADR-029 · 无论有无订阅者都进重放缓冲（连接空窗时也能补齐）
            buf = self._replay.get(channel)
            if buf is None:
                buf = deque(maxlen=_REPLAY_MAXLEN)
                self._replay[channel] = buf
            buf.append(evt)
            subs = self._channels.get(channel)
        if not subs:
            return
        for q in list(subs):
            if q.full():
                try:
                    q.get_nowait()  # drop oldest
                    logger.warning("[event_bus] channel=%s queue full; dropping oldest", channel)
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(evt)
            except Exception:
                logger.exception("[event_bus] put_nowait failed channel=%s", channel)

    async def subscribe(self, channel: uuid.UUID) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_MAX_QUEUE)
        async with self._lock:
            # 先注册队列（捕获此刻起的实时事件），再快照重放缓冲——同锁内原子，
            # 保证每条事件要么在 replay 快照、要么进 queue，不漏不重（前端仍幂等兜底）。
            self._channels.setdefault(channel, set()).add(q)
            cutoff = time.time() - _REPLAY_TTL_SEC
            replay = [e for e in self._replay.get(channel, ()) if e.get("ts", 0) >= cutoff]
        try:
            # ADR-029 · 零延迟补齐：订阅前/空窗 publish 的最近事件先重放，再无缝续接实时
            for evt in replay:
                yield evt
            while True:
                evt = await q.get()
                yield evt
        finally:
            async with self._lock:
                subs = self._channels.get(channel)
                if subs:
                    subs.discard(q)
                    if not subs:
                        self._channels.pop(channel, None)
                # 无订阅者且重放缓冲已全过期 → 回收，防长期泄漏
                buf = self._replay.get(channel)
                if buf is not None and channel not in self._channels:
                    cutoff = time.time() - _REPLAY_TTL_SEC
                    if not any(e.get("ts", 0) >= cutoff for e in buf):
                        self._replay.pop(channel, None)


class PgNotifyBackend(EventBusBackend):
    """v5.1 占位：将来跨进程部署时用 PostgreSQL LISTEN/NOTIFY 替代。

    不在 v5 接线；保留只是为了让 backend factory 早暴露 ABC 边界，避免后续 widespread refactor。
    """

    async def publish(self, channel: uuid.UUID, evt: dict[str, Any]) -> None:
        raise NotImplementedError("PgNotifyBackend 留作 v5.1 实现")

    def subscribe(self, channel: uuid.UUID) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError("PgNotifyBackend 留作 v5.1 实现")


# 全局单例 —— 任意模块 import bus 即可直接 publish/subscribe
bus: EventBusBackend = InProcessBus()


def reset_for_test() -> None:
    """测试用：清空所有 channel/subscriber。"""
    global bus
    bus = InProcessBus()
