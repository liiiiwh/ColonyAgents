"""ADR-008 P4 · WeChat Router 服务 · 自由消息 → 具体 super session。

轻量路由服务（非自主 super，无 tick/无调度）。一个微信账号服务 N 个 super
（MissionApprovalChannel 多对一）。审批回复/状态查询走 wechat_intent；这里只管
「用户想跟某个 super 说话」的自由消息：

  enumerate 候选 super（该 reviewer 可访问的 project）
   → decide_route（纯）：0空 / 1直达 / N→粘性·LLM语义·菜单
   → route：enqueue 到目标 super 的 pending 队列 + v7 idle-trigger + 记 sticky
   → ask：发编号菜单，暂存原文，待用户回编号
   → none：回「你还没有可对话的 super」

纯决策/缓存逻辑在 app/domain/wechat/router_policy.py（已 vitest/pytest 覆盖）。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.wechat.router_policy import (
    Candidate,
    commit_route,
    decide_route,
    parse_menu_choice,
    pending_text_for,
    stash_for_menu,
    sticky_for,
)
from app.models.approvals import WechatClawbotAccount

logger = logging.getLogger(__name__)


async def _candidates_for(
    db: AsyncSession, account: WechatClawbotAccount, wechat_user_id: str
) -> tuple[list[Candidate], dict[str, Any]]:
    """该 reviewer 在此 bot 下可对话的 super 候选 + mission_id→project 映射。"""
    from app.services.wechat_intent import list_reviewer_projects

    projects = await list_reviewer_projects(db, account, wechat_user_id)
    cands: list[Candidate] = []
    by_id: dict[str, Any] = {}
    for p in projects:
        pid = str(p.id)
        cands.append(
            Candidate(
                mission_id=pid,
                slug=p.slug,
                name=p.name,
                session_id=pid,  # 路由粒度 = super（project）；每 super 一个 daemon runtime
                description=_project_desc(p),
            )
        )
        by_id[pid] = p
    return cands, by_id


def _project_desc(project: Any) -> str:
    """给菜单/LLM 的一句话描述。goal_spec 已废弃（cand②：目标归 MissionMemory），
    用 mission 描述/名称兜底。"""
    try:
        return str(getattr(project, "description", None) or getattr(project, "name", None) or "")[:60]
    except Exception:  # noqa: BLE001
        return ""


async def route_inbound(
    db: AsyncSession,
    *,
    account: WechatClawbotAccount,
    wechat_user_id: str,
    user_text: str,
    llm_pick_slug: str | None = None,
    force_reroute: bool = False,
) -> dict[str, Any]:
    """主入口：把一条自由消息路由到某 super session（或发菜单消歧）。

    返回 {action: 'routed'|'ask'|'none', reply_text, target_slug?}
    """
    cands, by_id = await _candidates_for(db, account, wechat_user_id)
    cache = account.routing_cache or {}
    menu_choice = parse_menu_choice(user_text)
    cached_sticky = sticky_for(cache, wechat_user_id)

    decision = decide_route(
        candidates=cands,
        cached_session_id=cached_sticky,
        menu_choice=menu_choice,
        llm_pick_slug=llm_pick_slug,
        force_reroute=force_reroute,
    )

    if decision.kind == "none":
        return {
            "action": "none",
            "reply_text": "你在该 bot 下还没有可对话的 super（需先被加为该项目的审批人）。",
        }

    if decision.kind == "ask":
        # 暂存原文，待用户回编号后注入；若这条本身就是编号（无暂存原文），仍提示选择
        account.routing_cache = stash_for_menu(cache, wechat_user_id, user_text)
        await db.commit()
        return {"action": "ask", "reply_text": decision.menu_text}

    # decision.kind == "route"
    target = decision.target
    assert target is not None
    project = by_id.get(target.session_id)
    if project is None:
        return {"action": "none", "reply_text": "目标 super 已不可用，请重试。"}

    # 注入文本：若是「回编号」路由且有暂存原文，注入原文；否则注入本条
    inject_text = user_text
    if decision.reason == "menu_choice":
        stashed = pending_text_for(cache, wechat_user_id)
        if stashed:
            inject_text = stashed

    await _inject_and_trigger(db, project, inject_text, wechat_user_id)

    # 记 sticky、清 pending_text
    account.routing_cache = commit_route(cache, wechat_user_id, target.session_id)
    await db.commit()

    logger.info(
        "[wechat_router] routed wechat=%s → super=%s (%s) reason=%s",
        wechat_user_id, target.slug, target.session_id, decision.reason,
    )
    return {
        "action": "routed",
        "reply_text": f"已转给【{target.name}】，super 正在处理…",
        "target_slug": target.slug,
    }


async def _inject_and_trigger(
    db: AsyncSession, project: Any, text: str, wechat_user_id: str
) -> None:
    """把消息 enqueue 到目标 super 的 pending 队列 + v7 idle-trigger（idle 才立即起 tick）。"""
    from app.services import super_inbox
    from app.services.pending_queue import enqueue_user_message
    from app.domain.tick_policy import should_trigger_now

    try:
        await enqueue_user_message(
            db,
            project.id,
            project.supervisor_agent_id,
            text,
            meta={"source": "wechat_router", "wechat_user_id": wechat_user_id},
        )
    except Exception:  # noqa: BLE001
        logger.exception("[wechat_router] enqueue 失败 project=%s", project.id)
        return

    # v7 idle-trigger：super idle 立即起 tick；忙则排队，tick 完 auto-drain 接手
    runtime = getattr(project, "runtime_status", "") or ""
    if should_trigger_now(
        is_running=super_inbox.is_running(project.id), runtime_status=runtime
    ):
        try:
            import asyncio
            from app.api.super_conversation import _trigger_tick_async
            asyncio.create_task(
                _trigger_tick_async(project.id),
                name=f"wechat-route-tick-{project.id}",
            )
        except Exception:  # noqa: BLE001
            logger.exception("[wechat_router] trigger tick 失败 project=%s", project.id)
