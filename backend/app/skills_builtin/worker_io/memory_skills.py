"""Memory 工具族：读 / 写 / 追加当前 Agent 的持久化记忆。

scope 自动判定：
- 在 orchestrator session 中（branch_id 非空）→ BranchAgentMemory
- 在 daemon project 中（branch_id 为空 / memory_scope=project）→ MissionAgentMemory

memory_read：读当前 scope 的 memory.md
memory_write：整体覆写 memory.md（慎用；用于校正错误记忆）
memory_append：**主用**——追加一条带时间戳的 event 记录，不覆盖既有内容
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.domain.memory.consolidate import collapse_into
from app.services import memory_service
from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


class MemoryAppendArtifact(BaseModel):
    """memory_append 的 artifacts 数组元素。

    显式 schema —— 不能用 `list | None`（langchain 翻译成
    `anyOf:[{type:array},{type:null}]`，**没有 items 字段** → Gemini/Vertex AI
    严格拒绝 400 INVALID_ARGUMENT）。改成 `list[MemoryAppendArtifact] = []`，
    生成 `{type:array, items:{$ref:...}}`，所有 provider 都接受。
    """

    label: str = Field(description="产物标签，如「项目配置总结」")
    type: str = Field(description="产物类型：markdown / json / image / pdf 等")
    s3_url: str | None = Field(default=None, description="S3 URL（如有）")


def _scope(ctx: BuiltinToolContext) -> str:
    """ADR-018 mission-only · 选 scope：daemon→project(MissionAgentMemory)，否则→thread(ThreadAgentMemory)。"""
    if getattr(ctx, "memory_scope", None) == "project" and ctx.mission_id:
        return "project"
    if ctx.mission_id is not None and ctx.thread_key:
        return "thread"
    if ctx.mission_id is not None:
        return "project"
    return "thread"  # 兜底


def memory_read_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _read() -> str:
        if ctx.db_factory is None or not ctx.agent_node_name:
            return "❌ 工具上下文缺失（db_factory / agent_node_name）"
        scope = _scope(ctx)
        async with ctx.db_factory() as db:
            if scope == "project" and ctx.mission_id:
                mem = await memory_service.get_project_memory(
                    db, ctx.mission_id, ctx.agent_node_name
                )
                scope_label = "项目长期记忆"
            elif ctx.mission_id is not None and ctx.thread_key:
                mem = await memory_service.get_thread_memory(
                    db, ctx.mission_id, ctx.thread_key, ctx.agent_node_name
                )
                scope_label = "当前 thread 记忆"
            else:
                return "❌ 缺 mission_id / thread_key"
        if not mem or not mem.memory_md:
            return f"⚠️ 尚无{scope_label}（首次写入会自动初始化）"
        return f"# {scope_label}（已压缩 {mem.compressed_message_count} 条消息）\n\n{mem.memory_md}"

    return StructuredTool.from_function(
        coroutine=_read,
        name="memory_read",
        description=(
            "读取当前 Agent 的持久化记忆。无参数。"
            "scope 自动判定：在 builder chat 里读分支记忆；daemon 模式读项目记忆。"
        ),
    )


def memory_write_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _write(content: str) -> str:
        if ctx.db_factory is None or not ctx.agent_node_name:
            return "❌ 工具上下文缺失"
        if not content or not content.strip():
            return "❌ memory 内容不能为空"
        scope = _scope(ctx)
        async with ctx.db_factory() as db:
            if scope == "project" and ctx.mission_id:
                await memory_service.upsert_project_memory(
                    db, ctx.mission_id, ctx.agent_node_name,
                    content.strip(), compressed_count=0,
                )
            elif ctx.mission_id is not None and ctx.thread_key:
                await memory_service.upsert_thread_memory(
                    db, ctx.mission_id, ctx.thread_key, ctx.agent_node_name,
                    content.strip(), compressed_count=0,
                )
            else:
                return "❌ 缺 mission_id / thread_key"
        logger.info("🧠 memory_write[%s]: agent=%s size=%d", scope, ctx.agent_node_name, len(content))
        return f"✅ 已更新 {ctx.agent_node_name} 的{scope}记忆（{len(content)} 字符；覆写式）"

    return StructuredTool.from_function(
        coroutine=_write,
        name="memory_write",
        description=(
            "**覆写式**更新当前 Agent 记忆——会替换 memory.md 整体内容。"
            "**慎用**：通常应该用 `memory_append` 追加条目；只有需要重写整段错误记忆时才用这个。"
        ),
    )


def memory_append_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _append(
        event: str,
        progress: str = "",
        artifacts: list[MemoryAppendArtifact] | None = None,
        decision: str = "",
        next_step: str = "",
        extra_json: str = "",
    ) -> str:
        """**追加**一条带时间戳的事件记录到当前 Agent 的 memory 末尾——主要的记忆写入入口。

        Args:
            event: 本次事件简述（必填，≤200 字），如「mission_create 成功 / smoke test PASS / 用户审批通过」
            progress: 总体进度，如「3/5 步完成；待装 skill」
            artifacts: 本次产物清单 `[{label, type, s3_url?}, ...]`
            decision: 关键决策点，如「选用方案 A / 跳过 ClawHub 装新 skill」
            next_step: 下一步建议，让下一轮 turn 启动时 Supervisor 能继续推进
            extra_json: 任意元信息的 JSON 字符串（如 `'{"agent_id":"...","schedule_id":"..."}'`）
                       —— 用字符串而不是 dict 是为了兼容 Gemini/Vertex AI（不接受无 schema 的 dict）

        效果：在 memory.md 末尾追加结构化 markdown 段，**不覆盖**既有内容。
        """
        if ctx.db_factory is None or not ctx.agent_node_name:
            return "❌ 工具上下文缺失"
        if not event or not event.strip():
            return "❌ event 必填"
        # E4：extra_json 既接受 JSON 字符串也接受 dict（LLM 可能不读 docstring 直接传 dict）
        extra: dict | None = None
        if extra_json:
            import json as _json
            try:
                if isinstance(extra_json, dict):
                    extra = extra_json
                elif isinstance(extra_json, str):
                    parsed = _json.loads(extra_json)
                    if isinstance(parsed, dict):
                        extra = parsed
                    else:
                        # E11：解析成功但不是 dict（e.g. 是 list / 字符串）→ 返回错误而非塞 _raw
                        return (
                            f"❌ extra_json 必须是 JSON 对象（{{}}）字符串或 dict，"
                            f"当前解析出 {type(parsed).__name__}"
                        )
            except _json.JSONDecodeError as exc:
                # E11：JSON 解析失败 → 返回错误而非塞 _raw（避免脏数据）
                return (
                    f"❌ extra_json JSON 解析失败：{exc}。"
                    f"请传合法 JSON 字符串如 '{{\"agent_id\":\"...\"}}' 或直接 dict。"
                )
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines = [f"### [{ts}] {event.strip()}"]
        if progress:
            lines.append(f"- **progress**: {progress.strip()}")
        if decision:
            lines.append(f"- **decision**: {decision.strip()}")
        if next_step:
            lines.append(f"- **next**: {next_step.strip()}")
        # E10：artifacts=[] 不生成空段
        if artifacts and len(artifacts) > 0:
            real_artifacts = []
            for a in artifacts:
                if isinstance(a, MemoryAppendArtifact):
                    real_artifacts.append((a.label, a.type, a.s3_url or ""))
                elif isinstance(a, dict):
                    real_artifacts.append((
                        a.get("label", "(no label)"),
                        a.get("type", "?"),
                        a.get("s3_url", ""),
                    ))
            if real_artifacts:
                lines.append("- **artifacts**:")
                for label, atype, s3 in real_artifacts:
                    s3_hint = f" — `{s3}`" if s3 else ""
                    lines.append(f"  - {label} ({atype}){s3_hint}")
        if extra:
            try:
                import json as _json
                lines.append(f"- **extra**: `{_json.dumps(extra, ensure_ascii=False)}`")
            except Exception:
                lines.append(f"- **extra**: `{extra}`")
        seg = "\n".join(lines)

        # cand② · 收敛走 MemoryStore 的确定性核心 collapse_into：在**任意位置**识别近重复
        # （非只比最后一段）→ 折成「×N」并移末尾，治「跳过本轮」一天刷十几万字符的 bug。
        _collapsed = False

        scope = _scope(ctx)
        async with ctx.db_factory() as db:
            if scope == "project" and ctx.mission_id:
                existing = await memory_service.get_project_memory(
                    db, ctx.mission_id, ctx.agent_node_name
                )
                merged, _collapsed = collapse_into((existing.memory_md if existing else "") or "", seg)
                if existing:
                    existing.memory_md = merged
                    existing.last_compressed_at = datetime.now(UTC)
                    await db.commit()
                else:
                    await memory_service.upsert_project_memory(
                        db, ctx.mission_id, ctx.agent_node_name,
                        merged, compressed_count=0,
                    )
            elif ctx.mission_id is not None and ctx.thread_key:
                existing = await memory_service.get_thread_memory(
                    db, ctx.mission_id, ctx.thread_key, ctx.agent_node_name
                )
                merged, _collapsed = collapse_into((existing.memory_md if existing else "") or "", seg)
                if existing:
                    existing.memory_md = merged
                    existing.last_compressed_at = datetime.now(UTC)
                    await db.commit()
                else:
                    await memory_service.upsert_thread_memory(
                        db, ctx.mission_id, ctx.thread_key, ctx.agent_node_name,
                        merged, compressed_count=0,
                    )
            else:
                return "❌ 缺 mission_id / thread_key"

        if _collapsed:
            return (
                f"⏭️ 已折叠重复事件「{event[:40]}」→ 计数 +1，记忆不增长。"
                "情况有变（用户回复 / 错误变更 / 状态推进）请写**实际差异**。"
            )

        logger.info("🧠 memory_append[%s]: agent=%s event=%r", scope, ctx.agent_node_name, event[:60])
        return f"✅ 已追加事件「{event[:40]}」到 {ctx.agent_node_name} 的{scope}记忆"

    return StructuredTool.from_function(
        coroutine=_append,
        name="memory_append",
        description=(
            "**追加**一条带时间戳的事件到当前 Agent 的 memory（不覆盖既有内容）。"
            "用于持续记录：完成的关键动作 / 产生的产物 meta / 用户决策 / 下一步计划。"
            "下次 turn 启动时 Supervisor 会自动读到这条记录，保持计划连续。"
        ),
    )
