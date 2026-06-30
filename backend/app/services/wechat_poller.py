"""微信 Clawbot 长轮询后台任务：从每个 enabled 账号拉用户回复，匹配 pending_approvals。

启动：app.main.lifespan 里调 `start_pollers()`，每个 enabled WechatClawbotAccount 起一个独立
asyncio 协程跑 getUpdates 长轮询循环。

匹配规则（容错宽松，避免审批人输错就被拒）：
- 解析用户消息文本，找首个出现的 [a-f0-9]{8} 短串作为 request_id 候选
- 候选与 pending_approvals.request_id 匹配 → 取该 row.options
- 解析消息中提到的选项关键字（精确包含 或 「1/2/A/B」编号映射到第 N 个）
- 命中 → 调 pending_approval_service.decide(option=..., decided_by=f'wechat:{from_user_id}')
- 不命中 → 回个友好提示让对方重发

任意账号轮询失败不影响其他账号；连续 5 次失败就把该账号标 disabled 并写 last_error。
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt
from app.db.session import AsyncSessionLocal
from app.models.approvals import WechatClawbotAccount

logger = logging.getLogger(__name__)

_TASKS: dict[uuid.UUID, asyncio.Task] = {}
_STOP_EVENT: asyncio.Event | None = None

# 短 ID 匹配（8 位十六进制）
_REQID_RE = re.compile(r"\b([a-f0-9]{8})\b")
_NUM_RE = re.compile(r"^\s*(\d+)\s*[.、)\s]")


def _pick_option(text: str, options: list[str]) -> str | None:
    """从用户回复里挑出对应的选项。

    规则（按优先级）：
    1. 文本包含完整 option 字符串 → 返回该 option
    2. 文本以 "1." / "1、" / "1 " 开头 → 用 options[0]（同理 2/3/4）
    3. 文本为纯数字 → 同上
    4. 都不命中 → None（让 poller 回 prompt）
    """
    s = text.strip()
    if not options:
        return None
    # 1) 完整包含
    for opt in options:
        if opt and opt in s:
            return opt
    # 2/3) 数字编号
    m = _NUM_RE.match(s)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(options):
            return options[idx]
    if s.isdigit():
        idx = int(s) - 1
        if 0 <= idx < len(options):
            return options[idx]
    return None


async def _send_text(account: WechatClawbotAccount, to_user_id: str, text: str) -> None:
    """简单包装 wechat_clawbot.send_text，带 context_token 缓存。"""
    from app.services import wechat_clawbot

    token = decrypt(account.bot_token)
    ctx_tokens = account.context_tokens or {}
    try:
        await wechat_clawbot.send_text(
            token=token,
            base_url=account.base_url,
            to_user_id=to_user_id,
            text=text,
            context_token=str(ctx_tokens.get(to_user_id, "")),
        )
    except Exception:  # noqa: BLE001
        logger.exception("[wechat_poller] 回复用户 %s 失败", to_user_id)


async def _handle_message(
    db: AsyncSession,
    account: WechatClawbotAccount,
    msg: dict,
) -> None:
    """处理一条来自微信用户的消息：LLM 判意图（审批/查状态/含糊），自然语言回复。

    保留权限校验和 context_token 缓存；核心识别逻辑下放到 wechat_intent.classify_and_reply。
    """
    from app.models.approvals import MissionApprovalChannel
    from app.services import pending_approval_service, wechat_intent

    text = msg["text"]
    from_user_id = msg["from_user_id"]
    ctx_token = msg.get("context_token") or ""
    if not from_user_id:
        return

    # 更新 context_token 缓存（**关键**：回复必带 context_token；微信 ilink 不允许 bot 在用户
    # 没主动发消息前就 push，所以这个 token 是从入站消息抓的，作为后续回复的凭证）
    ct_map = dict(account.context_tokens or {})
    if ctx_token:
        ct_map[from_user_id] = ctx_token
        account.context_tokens = ct_map
        await db.commit()

    # 是否是 reviewer
    is_reviewer = from_user_id in list(account.reviewers or [])
    if not is_reviewer:
        channels = (
            await db.execute(
                select(MissionApprovalChannel).where(
                    MissionApprovalChannel.clawbot_account_id == account.id
                )
            )
        ).scalars().all()
        is_reviewer = any(from_user_id in (c.reviewer_wechat_ids or []) for c in channels)
    if not is_reviewer:
        await _send_text(
            account, from_user_id,
            "您不在审批人名单。请联系 Colony 管理员把您的 WeChat ID 加进项目审批人列表。",
        )
        return

    # ⭐ 用户对话首次打通后，把积压的 outbox（之前主动推送失败的）一次性吐给他
    try:
        from app.services import wechat_outbox
        flushed = await wechat_outbox.flush_for_user(
            db, account_id=account.id, wechat_user_id=from_user_id
        )
        if flushed:
            logger.info("[wechat_poller] flushed %d 条积压消息给 %s", flushed, from_user_id)
    except Exception:  # noqa: BLE001
        logger.exception("[wechat_poller] outbox flush 失败")

    # ADR-008 P4 · WeChat Router 菜单快捷路：用户正处于「选 super」菜单中且回了编号，
    # 直接路由（注入暂存原文），跳过 LLM 意图分类。
    try:
        from app.domain.wechat.router_policy import parse_menu_choice, pending_text_for
        from app.services import wechat_router
        if parse_menu_choice(text) is not None and pending_text_for(account.routing_cache or {}, from_user_id):
            res = await wechat_router.route_inbound(
                db, account=account, wechat_user_id=from_user_id, user_text=text,
            )
            await _send_text(account, from_user_id, res.get("reply_text") or "已处理。")
            return
    except Exception:  # noqa: BLE001
        logger.exception("[wechat_poller] 菜单快捷路由失败（降级走 LLM 分类）")

    # LLM 判意图
    try:
        intent = await wechat_intent.classify_and_reply(
            db, account=account, wechat_user_id=from_user_id, user_text=text
        )
    except Exception:  # noqa: BLE001
        logger.exception("[wechat_poller] 意图分类失败")
        await _send_text(account, from_user_id, "处理消息时出错；请稍后再说一次或换种说法。")
        return

    action = intent.get("intent")
    reply = intent.get("reply_text") or "已收到。"

    if action == "decide_approval":
        rid = intent.get("request_id")
        opt = intent.get("option")
        if rid and opt:
            row = await pending_approval_service.decide(
                db, request_id=rid, option=opt, decided_by=f"wechat:{from_user_id}",
            )
            if row is None:
                await _send_text(account, from_user_id, f"未找到审批 [{rid}]，可能已过期。")
                return
            # v5 · 微信决策也同步给前端 inline 卡片
            try:
                from app.services.event_bus import bus as _bus
                if row.mission_id:  # ADR-018 step 3b · channel = Mission (mission_id)
                    await _bus.publish(row.mission_id, {
                        "type": "approval_resolved",
                        "request_id": str(row.request_id),
                        "option": opt,
                        "decided_by": f"wechat:{from_user_id}",
                        "via": "wechat",
                    })
            except Exception:
                pass
        await _send_text(account, from_user_id, reply)
        return

    if action == "chat_to_super":
        # ADR-008 P4 · 自由消息 → 路由到具体 super session（LLM 给的 slug 作语义提示）
        try:
            from app.services import wechat_router
            res = await wechat_router.route_inbound(
                db, account=account, wechat_user_id=from_user_id, user_text=text,
                llm_pick_slug=intent.get("target_project_slug"),
            )
            await _send_text(account, from_user_id, res.get("reply_text") or reply)
        except Exception:  # noqa: BLE001
            logger.exception("[wechat_poller] chat_to_super 路由失败")
            await _send_text(account, from_user_id, "转发给 super 时出错，请稍后再试。")
        return

    # query_status / unclear / other —— 把 LLM 的回复发给用户
    await _send_text(account, from_user_id, reply)


async def _poll_one(account_id: uuid.UUID) -> None:
    """一个账号的长轮询循环。直到 STOP_EVENT 或被外部 cancel。"""
    from app.services import wechat_clawbot

    consecutive_errors = 0
    while True:
        if _STOP_EVENT and _STOP_EVENT.is_set():
            return
        try:
            async with AsyncSessionLocal() as db:
                acc = await db.get(WechatClawbotAccount, account_id)
                if acc is None:
                    logger.info("[wechat_poller] %s 已删除，退出", account_id)
                    return
                if not acc.is_enabled:
                    await asyncio.sleep(15)  # disabled 时低频复查
                    continue
                token = decrypt(acc.bot_token)
                base_url = acc.base_url
                sync_buf = acc.sync_buffer or ""

            resp = await wechat_clawbot.get_updates(
                token=token, base_url=base_url, sync_buffer=sync_buf
            )
            # token 过期
            errcode = resp.get("errcode") or resp.get("ret") or 0
            if errcode == -14:
                async with AsyncSessionLocal() as db:
                    acc = await db.get(WechatClawbotAccount, account_id)
                    if acc is not None:
                        acc.is_enabled = False
                        acc.last_error = "session expired (errcode=-14)；需要重新扫码登录"
                        acc.last_polled_at = datetime.now(UTC)
                        await db.commit()
                logger.warning("[wechat_poller] %s session 过期，禁用", account_id)
                return

            msgs = wechat_clawbot.parse_text_messages(resp)
            new_buf = resp.get("get_updates_buf") or sync_buf

            async with AsyncSessionLocal() as db:
                acc = await db.get(WechatClawbotAccount, account_id)
                if acc is None:
                    return
                acc.sync_buffer = new_buf
                acc.last_polled_at = datetime.now(UTC)
                acc.last_error = None
                await db.commit()
                for m in msgs:
                    try:
                        await _handle_message(db, acc, m)
                    except Exception:  # noqa: BLE001
                        logger.exception("[wechat_poller] 处理消息失败：%s", m)

            consecutive_errors = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            consecutive_errors += 1
            backoff = min(30, 2 * consecutive_errors)
            logger.warning(
                "[wechat_poller] %s 轮询失败 (#%d，%ss 后重试): %s",
                account_id, consecutive_errors, backoff, exc,
            )
            await asyncio.sleep(backoff)
            if consecutive_errors >= 8:
                async with AsyncSessionLocal() as db:
                    acc = await db.get(WechatClawbotAccount, account_id)
                    if acc is not None:
                        acc.last_error = f"connection error ×8: {exc}"
                        await db.commit()


async def start_pollers() -> None:
    """启动所有 enabled 账号的 poller。lifespan 起服时调用。"""
    global _STOP_EVENT
    _STOP_EVENT = asyncio.Event()
    async with AsyncSessionLocal() as db:
        accounts = (
            await db.execute(
                select(WechatClawbotAccount).where(WechatClawbotAccount.is_enabled.is_(True))
            )
        ).scalars().all()
    for acc in accounts:
        if acc.id in _TASKS and not _TASKS[acc.id].done():
            continue
        _TASKS[acc.id] = asyncio.create_task(
            _poll_one(acc.id), name=f"wechat-poller-{acc.name}"
        )
    logger.info("[wechat_poller] 启动 %d 个 poller", len(_TASKS))


async def stop_pollers() -> None:
    global _STOP_EVENT
    if _STOP_EVENT:
        _STOP_EVENT.set()
    for t in _TASKS.values():
        t.cancel()
    _TASKS.clear()


def start_for_account(account_id: uuid.UUID) -> None:
    """新建账号后立刻为它起 poller（避免等下次重启）。"""
    if account_id in _TASKS and not _TASKS[account_id].done():
        return
    _TASKS[account_id] = asyncio.create_task(
        _poll_one(account_id), name=f"wechat-poller-{account_id}"
    )


__all__ = ("start_pollers", "stop_pollers", "start_for_account")
