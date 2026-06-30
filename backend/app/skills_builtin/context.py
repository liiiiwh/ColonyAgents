"""BuiltinToolContext：工具运行时所需的上下文对象。

Agent 每次执行时由 `agent_service.build_agent_executor` 构建，注入各工具工厂。
含：
- 当前 Session / Branch / Agent 节点标识
- `event_queue`：工具可向其 put SSE 事件（`data-artifact` 等），由 chat endpoint 合并到流中
- `db_factory`：供工具按需创建新的 DB Session（避免共享同一 Session 在工具协程中长占）
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


DbSessionFactory = Callable[[], "AsyncSession"]


@dataclass
class BuiltinToolContext:
    """内置工具运行时上下文。"""

    agent_node_name: str | None = None
    mission_id: uuid.UUID | None = None
    # ADR-018 step5/H · thread 身份 = (mission_id=mission_id, thread_key)。
    # append_message / 记忆 / 压缩都按这个键；branch_id/session_id 退役中（Slice X 删）。
    thread_key: str | None = None

    # 工具向 chat SSE 流推送自定义事件（如 data-artifact）
    event_queue: asyncio.Queue[dict] | None = None

    # 工具按需获取新的 DB Session（回调返回 AsyncSession 实例）
    db_factory: DbSessionFactory | None = None

    # ── 提前终止信号 ──
    # 当 supervisor 调用 `request_approval` / `request_structured_input` 等
    # "请求用户输入即应结束本轮"的工具时，工具体在 emit 卡片后 set 此 event；
    # `stream_service._drive_llm` 在对应 on_tool_end 后立刻 break astream_events，
    # 避免 LLM 再 iterate 一轮生成"请在卡片上选择"那种无意义文本。
    # 同时也避免颁布"supervisor 说一段 + 弹卡 + 又说一段"的奇怪 UX。
    cancel_event: asyncio.Event | None = None

    # 当前正在执行的 Agent 是否生产"交付物"（来自 Agent.produces_deliverable）。
    # 影响 workspace_write 的落地行为：
    #   True  → 上传 S3 + 覆盖同节点 artifacts + 推送 data-artifact 给前端 Workspace 面板
    #   False → 只保存到 node.state（不上传 S3，不出现在 Workspace 面板 / 交付物进度条）
    produces_deliverable: bool = False

    # 当前 Agent UUID（用于 S3 路径 / 审计）
    agent_id: uuid.UUID | None = None

    # M3：记忆范围
    # - "branch"：从 `branch_agent_memories` 读写（Orchestrator 多对话；branch_id 必须）
    # - "project"：从 `mission_agent_memory` 读写（Daemon 长期运行；mission_id 必须）
    memory_scope: str = "branch"

    # 扩展字段：后续 phase 按需补充
    extra: dict[str, Any] = field(default_factory=dict)

    async def emit(self, event: dict) -> None:
        """向 chat SSE 事件队列推送一条事件。队列未绑定时静默忽略。"""
        if self.event_queue is not None:
            await self.event_queue.put(event)
