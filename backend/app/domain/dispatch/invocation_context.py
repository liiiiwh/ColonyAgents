"""R3-2 · InvocationContext · super↔worker 持久对话的代码家。

CONTEXT.md 命名禁忌：super↔worker 持久对话叫 **InvocationContext**。
之前散成 3 截（super_dispatch_skills 里 _THREAD_LOCKS / _get_or_create_super_worker_thread /
__load_thread_messages，相隔 430 LOC）。本类把它们收成一个东西：

    ic = InvocationContext(db, super_session_id, super_id, worker_id)
    async with ic.acquire():                 # V53 per-(super,worker) Lock
        branch, created = await ic.resolve_branch()
        history = await ic.load_history(exclude_latest=True)
        ...

不变式：
- 同 (super, worker) 对共享同一把 Lock（module-level registry，跨实例）
- thread_id（= thread_key）命名 `worker:{super_id}:{worker_id}`（全 UUID，ADR-020；
  弃用旧 `super-{sid8}-worker-{wid8}` 截断格式）
- resolve_branch 软幂等：先 SELECT 再 INSERT，并发失败重 SELECT
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import Any



# module-level lock registry：跨 InvocationContext 实例，同 key 共享同一把锁（V53）
_THREAD_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


def _get_thread_lock(super_id: uuid.UUID, worker_id: uuid.UUID) -> asyncio.Lock:
    key = (str(super_id), str(worker_id))
    lock = _THREAD_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _THREAD_LOCKS[key] = lock
    return lock


class InvocationContext:
    """一次（或一系列）super→worker 调用的持久对话上下文。"""

    def __init__(
        self,
        db: Any,
        *,
        super_session_id: uuid.UUID,
        super_id: uuid.UUID,
        worker_id: uuid.UUID,
    ) -> None:
        self.db = db
        self.super_session_id = super_session_id
        self.super_id = super_id
        self.worker_id = worker_id
        # ADR-020 · thread_key = worker:{super_id}:{worker_id}（全 UUID，命名即身份）
        self.thread_id = f"worker:{super_id}:{worker_id}"
        self.thread_lock = _get_thread_lock(super_id, worker_id)

    @contextlib.asynccontextmanager
    async def acquire(self):
        """持 per-(super,worker) Lock 的 async context manager。"""
        async with self.thread_lock:
            yield self

    # ADR-018 mission-only · resolve_branch 已删：thread 身份 = self.thread_id（纯字符串），
    # 由调用方直接作 thread_key 用，不再 find-or-create SessionBranch 行。

    async def load_history(self, mission_id, thread_key: str, *, exclude_latest: bool = False):
        """读 thread (mission_id, thread_key) 非压缩消息 → LangChain Message list（ADR-018 step5/H）。

        含 ThreadAgentMemory 压缩摘要作 SystemMessage（让 worker 看到历史）。
        """
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from app.services import memory_service, messaging_service

        msgs = await messaging_service.list_thread_messages(self.db, mission_id, thread_key)
        out: list = []
        try:
            mem = await memory_service.get_thread_memory(
                self.db, mission_id, thread_key, "worker_conversation"
            )
            if mem and (mem.memory_md or "").strip():
                out.append(SystemMessage(
                    content=f"<thread_history_compressed>\n{mem.memory_md[:20000]}\n</thread_history_compressed>"
                ))
        except Exception:
            pass
        converted: list = []
        for m in msgs:
            if m.is_compressed:
                continue
            content = (m.content or "").strip()
            if not content:
                continue
            if m.role == "user":
                converted.append(HumanMessage(content=content))
            elif m.role == "assistant":
                converted.append(AIMessage(content=content))
        if exclude_latest and converted and isinstance(converted[-1], HumanMessage):
            converted = converted[:-1]
        return out + converted
