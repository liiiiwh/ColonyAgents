"""R2-3 · MemoryReader · CONTEXT.md「3 层记忆」统一读路径。

3 层（CONTEXT.md > 记忆 3 层）：
- §1 MissionMemory  ← mission_agent_memory (按 mission_id + agent_node_name='supervisor')
- §2 SuperMemory    ← agents.domain_memory_md (角色级共享，跨 mission)
- §3 PlatformKB     ← knowledge_bases scope='platform' (本 reader 只输出 'see knowledge_search' 指针；
                      实际检索按 query 走 knowledge_search 工具)

意图：让 agent_service.build_agent_executor、mission_daemon.run_once、memory_skills 3 处不再
各自查 2-3 张表，统一过本 reader。
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def assemble_long_memory_md(
    db: AsyncSession,
    *,
    super_agent_id: Optional[uuid.UUID],
    mission_id: Optional[uuid.UUID],
    supervisor_node_name: str = "supervisor",
) -> str:
    """3 层 union，返回 ready-to-inject markdown。

    每层独立输出区段；为空时输出 `<!-- §X empty -->` 占位（让 LLM 不混淆段号）。
    """
    sections: list[str] = []

    # §1 MissionMemory
    mission_md = await _read_mission_memory(db, mission_id, supervisor_node_name)
    if mission_md:
        sections.append(f"## §1 · MissionMemory（mission 长期记忆）\n\n{mission_md}")
    else:
        sections.append("<!-- §1 MissionMemory empty -->")

    # §2 SuperMemory（agent.domain_memory_md，角色级共享）
    super_md = await _read_super_memory(db, super_agent_id)
    if super_md:
        sections.append(f"## §2 · SuperMemory（super 角色共享，跨 mission）\n\n{super_md}")
    else:
        sections.append("<!-- §2 SuperMemory empty -->")

    # §3 PlatformKB → 指针，不预注入（避免 prompt 爆量）
    sections.append(
        "## §3 · PlatformKB\n\n"
        "（跨 super 共享的经验/规则；按需用 `knowledge_search` 检索；不预注入）"
    )

    return "\n\n".join(sections)


async def _read_mission_memory(
    db: AsyncSession,
    mission_id: Optional[uuid.UUID],
    agent_node_name: str,
) -> str | None:
    if mission_id is None:
        return None
    from app.models.mission import MissionAgentMemory
    row = (await db.execute(
        select(MissionAgentMemory).where(
            MissionAgentMemory.mission_id == mission_id,
            MissionAgentMemory.agent_node_name == agent_node_name,
        ).limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    return (row.memory_md or "").strip() or None


async def _read_super_memory(
    db: AsyncSession,
    super_agent_id: Optional[uuid.UUID],
) -> str | None:
    if super_agent_id is None:
        return None
    from app.models.agent import Agent
    agent = await db.get(Agent, super_agent_id)
    if agent is None:
        return None
    md = (getattr(agent, "domain_memory_md", None) or "").strip()
    return md or None
