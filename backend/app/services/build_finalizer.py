"""ADR-013 · Builder 构建确定性收尾（不依赖 LLM 记得调）。

病根：工厂靠超长 LLM 协议让模型记得 mcp_ensure_ready + activate_super_first_run，模型一停就
留个半成品壳。解法：Builder tick 结束后，**代码**自动收尾它本会话建的 super 项目。

信号：mission_create 会把 Builder 会话的 target_project_id 指向新建项目 → tick 后据此 finalize。
幂等：已 finalize（存在 super_activated 消息）则跳过。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def maybe_finalize_after_builder_tick(
    db: AsyncSession, builder_project_id
) -> dict | None:
    """仅当 builder_project_id 是 Builder 项目时：finalize 它本 mission 建出的 super 项目。

    ADR-018 mission-only：通知写到 builder mission 的主 thread (builder_project_id, 'main')。"""
    from app.models.agent import Agent
    from app.models.mission import Mission

    proj = await db.get(Mission, builder_project_id)
    if proj is None:
        return None
    # 任何「Builder super 监管的 mission」都要收尾——不只主 builder mission(slug='builder')，
    # 也包括用户 +新建 的每场景设计会话（slug != 'builder'）。否则 +新建 建出的 super 永远
    # 没 schedule / 不自启。判定：supervisor 是 category='builder' 的 super。
    sup = await db.get(Agent, proj.supervisor_agent_id) if proj.supervisor_agent_id else None
    if sup is None or sup.category != "builder":
        return None
    # provenance 找本 builder mission 建出的 super 项目（取代 session.target_project_id）
    from app.services import mission_service
    built = await mission_service.get_mission_built_by_mission(db, builder_project_id)
    if built is None:
        return None
    return await finalize_super_build(db, built.id, builder_project_id, "main")


async def _bound_or_managed_mcp_ids(db: AsyncSession, mission_id) -> list:
    """该项目相关的本地 http MCP：先取绑到本 mission super 的（ADR-027 D5：worker MCP 由
    capability dispatch 动态解析，不再 mission_nodes 预绑）；没有则回退到系统里唯一一个
    「有 startup_command/manifest 的本地 http MCP」（单 colony 启发式）。"""
    pid = str(mission_id)
    bound = (await db.execute(text(
        "SELECT DISTINCT m.id FROM mcp_servers m "
        "JOIN agent_mcp_servers ams ON ams.mcp_server_id=m.id "
        "WHERE m.server_type='http' AND m.is_enabled IS TRUE AND "
        "  ams.agent_id IN (SELECT supervisor_agent_id FROM missions WHERE id=:p)"
    ), {"p": pid})).scalars().all()
    if bound:
        return list(bound)
    # 回退：系统中受管的本地 http MCP（有 startup_command 或 manifest）
    managed = (await db.execute(text(
        "SELECT id FROM mcp_servers WHERE server_type='http' AND is_enabled IS TRUE "
        "AND (startup_command IS NOT NULL OR readiness_manifest IS NOT NULL)"
    ))).scalars().all()
    return list(managed)


async def finalize_super_build(
    db: AsyncSession, mission_id, notify_mission_id, notify_thread_key
) -> dict:
    """确定性收尾：ensure_ready 相关本地 MCP（卡落本项目）+ 激活 super 首跑 + Builder 会话给进入按钮。

    幂等：已存在本项目的 super_activated 消息则跳过。
    """
    from app.models.mission import Mission
    from app.services import mission_daemon, readiness as rd, messaging_service

    proj = await db.get(Mission, mission_id)
    if proj is None or proj.supervisor_agent_id is None:
        return {"skipped": "no_supervisor"}

    pid = mission_id if isinstance(mission_id, uuid.UUID) else uuid.UUID(str(mission_id))
    actions: list[str] = []

    # 0. origin_session_id 确定性写入 —— **在 already-finalized 短路之前**做，
    # 这样即便 Builder LLM 自己调了 activate_super_first_run（已写 super_activated），
    # 也能确保 origin 被写上（否则 L3 escalation 只能靠 dispatcher 回退猜）。
    # ADR-018 mission-only：origin = 产出该 super 的 Builder mission（notify_mission_id）。
    # 历史 bug：此处曾引用已删的 notify_session_id（sessions 退役遗留），NameError 让收尾整段崩，
    # super 永远拿不到默认 schedule + 首跑激活。
    if notify_mission_id:
        try:
            wf = dict(proj.workflow_config or {})
            if not wf.get("origin_session_id"):
                wf["origin_session_id"] = str(notify_mission_id)
                proj.workflow_config = wf
                await db.commit()
                actions.append("origin_session_id")
        except Exception:  # noqa: BLE001
            logger.exception("[finalize] 写 origin_session_id 失败（不阻塞）project=%s", mission_id)

    already = (await db.execute(text(
        "SELECT 1 FROM messages WHERE meta->>'type'='super_activated' "
        "AND meta->>'project_slug'=:s LIMIT 1"
    ), {"s": proj.slug})).first()
    if already:
        return {"skipped": "already_finalized", "project_slug": proj.slug,
                "actions": actions}

    # 1. ensure_ready 相关本地 MCP（QR/密钥卡落到本 super 项目会话）
    try:
        for mid in await _bound_or_managed_mcp_ids(db, mission_id):
            await rd.ensure_ready_for_server(db, mid, mission_id=mission_id)
            actions.append(f"ensure_ready:{str(mid)[:8]}")
    except Exception:  # noqa: BLE001
        logger.exception("[finalize] ensure_ready 失败（不阻塞）project=%s", mission_id)

    # 1.6 调度由 Builder 结合场景决定，**不再强制补默认 cron**：
    #   - 周期性场景（如 SRE 巡检、日报）→ Builder 在 BUILD 阶段显式建 cron/interval schedule；
    #   - 事件/按需场景（如法律合同审查：上传合同才触发）→ 无 schedule，靠事件/用户消息驱动。
    # 旧逻辑无条件补 `*/3 * * * *` 默认 tick，会让事件驱动 super 每 3 分钟空跑烧 LLM（无意义）。
    # 首跑由下面 kickoff 保证；之后是否持续自动跑取决于 Builder 是否按场景建了 schedule。

    # 2. 激活 super 首跑（kickoff）
    try:
        await mission_daemon.start(db, pid, kickoff=True)
        actions.append("kickoff")
    except Exception:  # noqa: BLE001
        logger.exception("[finalize] kickoff 失败 project=%s", mission_id)

    # 3. Builder mission 主 thread 写 super_activated 消息 → 前端渲「进入 super →」按钮
    if notify_mission_id:
        try:
            await messaging_service.append_message(
                db, notify_mission_id, notify_thread_key or "main", role="agent_log",
                content=f"✅ {proj.name or proj.slug} 已建好并激活。点「进入 super →」进它的工作台，它会给你一份运营方案，确认或微调即可。",
                meta={"type": "super_activated", "project_slug": proj.slug,
                      "project_name": proj.name or proj.slug},
            )
            actions.append("button")
        except Exception:  # noqa: BLE001
            logger.exception("[finalize] 写 super_activated 消息失败")

    logger.info("[finalize] 确定性收尾 project=%s actions=%s", proj.slug, actions)
    return {"ok": True, "finalized": proj.slug, "actions": actions}
