"""L3 escalation dispatcher：把 worker-project supervisor 的升级信封异步投递到
原始 Builder Chat session。

模式：异步 create_task 投递后台 worker（绕过 supervisor LLM 直接执行）。
- fire-and-forget asyncio.create_task
- 投递 = 给 origin session current branch 写 role=system 消息（不自动唤醒 LLM）
- 同时 wechat_push_notification 给项目 reviewer（带 link 让用户点开）
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

logger = logging.getLogger(__name__)


async def deliver_escalation(escalation_id: uuid.UUID) -> None:
    """异步：把一条 escalation 投递到原始 Builder Chat session。

    流程：
      1. 查 escalation row + project
      2. 查 origin_session_id（在 project.workflow_config['origin_session_id']）
         - 没有 → status=dismissed + 写到项目记忆（无投递地址）
      3. 查 session 当前 branch
      4. append_message(role=system, content="[project-escalation #N]...")
      5. 标 escalations.status=delivered + delivered_at
      6. wechat 推送给项目 reviewer
    """
    from app.db.session import AsyncSessionLocal
    from app.models.mission import Mission, MissionEscalation
    from app.services import messaging_service

    async with AsyncSessionLocal() as db:
        esc = await db.get(MissionEscalation, escalation_id)
        if esc is None:
            logger.warning("[escalation] %s 不存在，跳过投递", escalation_id)
            return
        project = await db.get(Mission, esc.mission_id)
        if project is None:
            esc.status = "dismissed"
            await db.commit()
            return

        # ADR-018 mission-only · escalation 投递到产出该 super 的 origin builder mission 主 thread。
        # origin = super agent 的 built_by_mission_id（provenance）；不再经 session/branch。
        from app.models.agent import Agent as _Agent
        sup_agent = await db.get(_Agent, project.supervisor_agent_id) if project.supervisor_agent_id else None
        origin_mission_id = getattr(sup_agent, "built_by_mission_id", None) if sup_agent else None
        if origin_mission_id is None:
            logger.info(
                "📊 colony_l3_escalation_no_origin project=%s escalation=%s（super 无 built_by_mission_id）",
                project.id, escalation_id,
            )
            esc.status = "dismissed"
            await db.commit()
            return

        # 投递消息（role=agent_log，不自动触发 LLM）
        ev_blob = ""
        try:
            ev_blob = json.dumps(esc.evidence_json or {}, ensure_ascii=False)[:3000]
        except Exception:
            ev_blob = "(evidence 序列化失败)"
        content = (
            f"[project-escalation from {project.slug}] {esc.category}/{esc.severity}\n"
            f"{esc.summary}\n\n"
            f"<details>\n"
            f"escalation_id: {esc.id}\n"
            f"proposed_change: {esc.proposed_change[:1000]}\n"
            f"evidence: {ev_blob}\n"
            f"</details>"
        )
        # 用 agent_log 角色 + type=project_escalation；stream_service 把它重建为
        # HumanMessage 喂给 Builder LLM（system 角色会被静默丢弃）。
        # V45: super-initiated 标记（category='structural' 来自 super.request_new_capability）
        # 让前端能区分 user-initiated vs super-initiated 的 Builder Chat 消息
        msg_meta = {
            "type": "project_escalation",
            "escalation_id": str(esc.id),
            "mission_id": str(project.id),
            "project_slug": project.slug,
            "category": esc.category,
            "severity": esc.severity,
        }
        if esc.category == "structural" and project.supervisor_agent_id:
            msg_meta["opened_by"] = f"super:{project.supervisor_agent_id}"
            msg_meta["super_initiated"] = True
        await messaging_service.append_message(
            db,
            origin_mission_id,
            "main",
            role="agent_log",
            content=content,
            meta=msg_meta,
        )
        esc.status = "delivered"
        esc.delivered_at = datetime.now(UTC)
        await db.commit()

        # ADR-009 G3 · 立即唤醒 Builder（复用 v7 idle-trigger）：escalation 已落 Builder mission 主 thread，
        # 若 Builder idle 就立刻起一轮 tick 处理，不再等人来撩。ADR-018：builder mission = origin_mission_id。
        try:
            builder_pid = origin_mission_id
            if builder_pid is not None:
                from app.services import super_inbox
                from app.domain.tick_policy import should_trigger_now
                from app.models.mission import Mission as _Proj
                bproj = await db.get(_Proj, builder_pid)
                runtime = (bproj.runtime_status if bproj else "") or ""

                # ADR-028 D3 · daemon tick 不加载主线程历史 → 必须把「你有 N 条未处理升级」
                # 主动 enqueue 进 super_inbox pending queue，让 tick 上下文（auto-drain）即使不读
                # 主线程也能感知到本升级并优先处理。idle / busy 两路都喂，保证不漏。
                if bproj is not None and bproj.supervisor_agent_id is not None:
                    from app.skills_builtin.builder.escalation_skills import _count_unresolved
                    from app.services.pending_queue import enqueue_user_message
                    unresolved = await _count_unresolved(db, builder_pid)
                    await enqueue_user_message(
                        db, builder_pid, bproj.supervisor_agent_id,
                        f"[系统] 收到来自项目 {project.slug} 的新 project escalation"
                        f"（{esc.category}/{esc.severity}）#{unresolved}，请按 §0 优先处理。",
                        meta={
                            "source": "escalation_notification",
                            "escalation_id": str(esc.id),
                            "unresolved_count": unresolved,
                        },
                    )
                    logger.info(
                        "[escalation] 已 enqueue 升级通知进 builder super_inbox project=%s unresolved=%d",
                        builder_pid, unresolved,
                    )

                if should_trigger_now(
                    is_running=super_inbox.is_running(builder_pid), runtime_status=runtime,
                ):
                    import asyncio
                    from app.api.super_conversation import _trigger_tick_async
                    asyncio.create_task(
                        _trigger_tick_async(builder_pid),
                        name=f"escalation-wake-builder-{esc.id}",
                    )
                    logger.info("[escalation] 已 idle-trigger 唤醒 Builder project=%s", builder_pid)
                else:
                    # Builder 正忙：上面的 pending marker 会在 v7 tick 边界 auto-drain
                    # 被消费 → 当前 tick 结束后自动接着起一轮处理本 escalation（无需人工 nudge）。
                    logger.info(
                        "[escalation] Builder 忙 → 已入 pending marker，tick 边界 auto-drain 接手 project=%s",
                        builder_pid,
                    )
        except Exception:  # noqa: BLE001
            logger.exception("[escalation] auto-wake Builder 失败（不阻塞，等人来撩）")

    # wechat 推送（fire-and-forget；用现有 wechat_push_notification 内部实现）
    try:
        from app.models.approvals import MissionApprovalChannel
        async with AsyncSessionLocal() as db2:
            ch = (
                await db2.execute(
                    select(MissionApprovalChannel).where(
                        MissionApprovalChannel.mission_id == esc.mission_id,
                        MissionApprovalChannel.enabled.is_(True),
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if ch and ch.clawbot_account_id and (ch.reviewer_wechat_ids or []):
                # 复用 pending_approval_service._dispatch_to_wechat-like 逻辑
                # 简化版：直接写入 wechat_outbox 让现有 flush 流程发出
                from app.models.wechat_outbox import WechatOutbox
                row = WechatOutbox(
                    account_id=ch.clawbot_account_id,
                    mission_id=esc.mission_id,
                    target_wechat_id=(ch.reviewer_wechat_ids or [None])[0],
                    kind="notification",
                    content=(
                        f"⚠️ Mission [{esc.severity.upper()}] [{esc.category}]\n"
                        f"{esc.summary}\n"
                        f"打开 Builder Chat 处理（mission={str(origin_mission_id)[:8]}）"
                    )[:1000],
                    status="pending",
                )
                db2.add(row)
                await db2.commit()
    except Exception:
        logger.exception("[escalation] wechat push 失败（不阻塞投递）")

    logger.info(
        "📊 colony_l3_delivered project=%s escalation=%s origin_mission=%s",
        esc.mission_id, escalation_id, origin_mission_id,
    )


def fire_escalation(escalation_id: uuid.UUID) -> None:
    """从 sync 上下文里 fire-and-forget 一个投递。模仿
    与历史 daemon 审批后台派发同构的注册方式。
    """
    from app.core.bg_tasks import spawn
    spawn(
        deliver_escalation(escalation_id),
        name=f"escalation-deliver-{escalation_id}",
    )
