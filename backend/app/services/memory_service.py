"""Agent 记忆服务：项目级 / thread 级压缩记忆（memory_md）的读取与追加式 upsert。

记忆是压缩子系统的产物：旧对话被 LLM 摘要成自包含「压缩段」追加进 memory_md，
按 (mission_id, agent_node_name) 或 (mission_id, thread_key, agent_node_name) 索引。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import ThreadAgentMemory


# ── project-scoped memory（M3）──
async def get_project_memory(
    db: AsyncSession, mission_id: uuid.UUID, agent_node_name: str
):
    """读取项目级 Agent 记忆。结构与 BranchAgentMemory 一致。"""
    from app.models.mission import MissionAgentMemory

    result = await db.execute(
        select(MissionAgentMemory).where(
            MissionAgentMemory.mission_id == mission_id,
            MissionAgentMemory.agent_node_name == agent_node_name,
        )
    )
    return result.scalar_one_or_none()


async def upsert_project_memory(
    db: AsyncSession,
    mission_id: uuid.UUID,
    agent_node_name: str,
    memory_md: str,
    compressed_count: int,
    *,
    s3_key: str | None = None,
):
    """upsert 项目级 Agent 记忆。与 upsert_branch_memory 同语义。"""
    from app.models.mission import MissionAgentMemory

    existing = await get_project_memory(db, mission_id, agent_node_name)
    now = datetime.now(UTC)
    if existing:
        # 追加且自包含：每段携带独立编号 + 时间戳 + 起止注释边界
        ts = now.strftime("%Y-%m-%d %H:%M")
        prev_count = (existing.memory_md or "").count("## 压缩段 #")
        seq_no = prev_count + 1
        new_total = (existing.compressed_message_count or 0) + compressed_count
        seg = (
            f"\n\n---\n"
            f"## 压缩段 #{seq_no}（~{ts}，本次 +{compressed_count} 条，累计 {new_total} 条）\n"
            f"<!-- 该段为独立摘要，不引用其他段落 -->\n\n"
            f"{(memory_md or '').strip()}\n\n"
            f"<!-- end 压缩段 #{seq_no} -->"
        )
        existing.memory_md = (existing.memory_md or "") + seg
        existing.compressed_message_count = new_total
        existing.last_compressed_at = now
        if s3_key:
            existing.s3_key = s3_key
        await db.commit()
        await db.refresh(existing)
        return existing
    created = MissionAgentMemory(
        mission_id=mission_id,
        agent_node_name=agent_node_name,
        memory_md=memory_md,
        compressed_message_count=compressed_count,
        s3_key=s3_key,
        last_compressed_at=now,
    )
    db.add(created)
    await db.commit()
    await db.refresh(created)
    return created


# ── thread-scoped memory ──
async def get_thread_memory(
    db: AsyncSession, mission_id: uuid.UUID, thread_key: str, agent_node_name: str
) -> ThreadAgentMemory | None:
    """ADR-018 Phase B · read compression memory by the target keying (mission_id, thread_key)."""
    return (
        await db.execute(
            select(ThreadAgentMemory).where(
                ThreadAgentMemory.mission_id == mission_id,
                ThreadAgentMemory.thread_key == thread_key,
                ThreadAgentMemory.agent_node_name == agent_node_name,
            )
        )
    ).scalar_one_or_none()


async def upsert_thread_memory(
    db: AsyncSession,
    mission_id: uuid.UUID,
    thread_key: str,
    agent_node_name: str,
    memory_md: str,
    compressed_count: int,
    *,
    s3_key: str | None = None,
) -> ThreadAgentMemory:
    """ADR-018 step5/K · thread 原生记忆 upsert（无 branch 镜像）。

    与 upsert_branch_memory 同语义（追加自包含压缩段），但直接读写 ThreadAgentMemory，
    键为 (mission_id, thread_key, agent_node_name)。压缩子系统唯一的记忆写入口。
    """
    existing = await get_thread_memory(db, mission_id, thread_key, agent_node_name)
    now = datetime.now(UTC)
    if existing:
        ts = now.strftime("%Y-%m-%d %H:%M")
        prev_count = (existing.memory_md or "").count("## 压缩段 #")
        seq_no = prev_count + 1
        new_total = (existing.compressed_message_count or 0) + compressed_count
        seg = (
            f"\n\n---\n"
            f"## 压缩段 #{seq_no}（~{ts}，本次 +{compressed_count} 条，累计 {new_total} 条）\n"
            f"<!-- 该段为独立摘要，不引用其他段落 -->\n\n"
            f"{(memory_md or '').strip()}\n\n"
            f"<!-- end 压缩段 #{seq_no} -->"
        )
        existing.memory_md = (existing.memory_md or "") + seg
        existing.compressed_message_count = new_total
        existing.last_compressed_at = now
        if s3_key:
            existing.s3_key = s3_key
        await db.commit()
        await db.refresh(existing)
        return existing
    created = ThreadAgentMemory(
        mission_id=mission_id,
        thread_key=thread_key,
        agent_node_name=agent_node_name,
        memory_md=memory_md,
        compressed_message_count=compressed_count,
        last_compressed_at=now,
        s3_key=s3_key,
    )
    db.add(created)
    await db.commit()
    await db.refresh(created)
    return created
