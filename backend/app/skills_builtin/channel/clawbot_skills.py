"""微信 Clawbot 审批渠道 - Builder Supervisor 专用工具集。

让 Builder 在 /orchestrator chat 里引导用户绑定微信审批通道：
- `clawbot_login_start` → 拿二维码 URL，前端 / Builder 把这个 URL 给用户去用浏览器打开扫
- `clawbot_login_confirm` → 阻塞等扫码完成，扫完入库
- `list_clawbot_accounts` → 看现有账号
- `mission_set_approval_channel` → 把账号 + 项目审批人绑给某个 worker project

设计：每个工具调用都在 Builder Mission 上下文（ctx.mission_id=builder）。
"""

from __future__ import annotations

import logging
import uuid

from langchain_core.tools import StructuredTool

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


def clawbot_login_start_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _run() -> dict:
        """拉一个微信扫码登录 session，返回**可直接嵌入聊天的 PNG URL**。"""
        from app.services import wechat_clawbot
        try:
            res = await wechat_clawbot.get_qrcode()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"拉二维码失败: {exc}"}
        if not res.get("qrcode_session"):
            return {"ok": False, "error": "服务端返回空 qrcode_session"}
        return {
            "ok": True,
            "qrcode_session": res["qrcode_session"],
            "qrcode_img_url": res["qrcode_img_url"],
            "qrcode_inline_img_url": res["qrcode_inline_img_url"],
            "next_step": (
                "**关键**：弹 request_approval 时，message 里**必须**用 markdown 把二维码直接嵌进来，"
                "用户扫卡片里的图就行，不要让用户去点链接。模板：\n\n"
                "```\n请用微信「扫一扫」扫描下方二维码：\n\n"
                "![微信二维码]({qrcode_inline_img_url})\n\n"
                "扫描后在微信里确认登录。扫完点「我扫好了」，我会自动把账号入库并配置审批人。\n"
                "```\n\n"
                "options=['我扫好了', '取消']。用户点「我扫好了」后立即调 "
                "clawbot_login_confirm(qrcode_session, name=..., reviewers=...)。"
            ),
        }

    return StructuredTool.from_function(
        coroutine=_run,
        name="clawbot_login_start",
        description=(
            "（Builder 专用）启动微信 Clawbot 扫码登录流程，返回二维码图片 URL。"
            "把 URL 在 approval 卡片里给用户扫；用户扫码确认后再调 clawbot_login_confirm。"
            "无参数。"
        ),
    )


def clawbot_login_confirm_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _run(
        qrcode_session: str,
        name: str,
        description: str = "",
        reviewers: list[str] | None = None,
        max_poll_seconds: int = 240,
    ) -> dict:
        """阻塞轮询扫码状态直到 confirmed/expired/timeout，confirmed 后把账号入库。"""
        import asyncio
        from app.core.encryption import encrypt
        from app.models.approvals import WechatClawbotAccount
        from app.services import wechat_clawbot, wechat_poller
        from sqlalchemy import select

        if ctx.db_factory is None:
            return {"ok": False, "error": "db_factory not available"}
        if not (qrcode_session or "").strip():
            return {"ok": False, "error": "qrcode_session 不能空"}
        if not (name or "").strip():
            return {"ok": False, "error": "name 不能空（用户起的账号名）"}

        # 重名检查
        async with ctx.db_factory() as db:
            existing = (
                await db.execute(
                    select(WechatClawbotAccount).where(
                        WechatClawbotAccount.name == name.strip()
                    )
                )
            ).scalar_one_or_none()
            if existing:
                return {"ok": False, "error": f"账号 name={name!r} 已存在"}

        deadline = asyncio.get_event_loop().time() + max(30, min(max_poll_seconds, 480))
        confirmed: dict = {}
        while True:
            if asyncio.get_event_loop().time() > deadline:
                return {"ok": False, "error": "扫码超时（用户未在期限内扫码）"}
            try:
                res = await wechat_clawbot.poll_qrcode_status(qrcode_session)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[clawbot_login_confirm] poll 异常 %s（继续）", exc)
                await asyncio.sleep(2)
                continue
            st = res.get("status")
            if st == "confirmed":
                confirmed = res
                break
            if st == "expired":
                return {"ok": False, "error": "二维码已过期，请重新 clawbot_login_start"}
            await asyncio.sleep(1.5)

        bot_token = confirmed.get("bot_token") or ""
        base_url = confirmed.get("baseurl") or wechat_clawbot.ILINK_DEFAULT_BASE
        ilink_bot_id = confirmed.get("ilink_bot_id") or ""
        if not bot_token or not ilink_bot_id:
            return {"ok": False, "error": f"扫码 OK 但字段缺失: {confirmed}"}

        created_by_raw = ctx.extra.get("acting_user_id")
        created_by = None
        if created_by_raw:
            try:
                created_by = uuid.UUID(str(created_by_raw))
            except (ValueError, TypeError):
                pass

        async with ctx.db_factory() as db:
            acc = WechatClawbotAccount(
                name=name.strip(),
                description=(description or "").strip(),
                bot_token=encrypt(bot_token),
                base_url=base_url,
                ilink_bot_id=ilink_bot_id,
                ilink_user_id=confirmed.get("ilink_user_id"),
                sync_buffer="",
                context_tokens={},
                reviewers=list(reviewers or []),
                is_enabled=True,
                created_by=created_by,
            )
            db.add(acc)
            await db.commit()
            await db.refresh(acc)
        # 立即起 poller
        try:
            wechat_poller.start_for_account(acc.id)
        except Exception:  # noqa: BLE001
            logger.exception("[clawbot_login_confirm] start_for_account 失败")
        return {
            "ok": True,
            "clawbot_account_id": str(acc.id),
            "name": acc.name,
            "ilink_bot_id": acc.ilink_bot_id,
            "reviewers_count": len(acc.reviewers or []),
            "next_step": (
                "调 mission_set_approval_channel(target_project_id, clawbot_account_id, "
                "reviewer_wechat_ids=[]) 把这个账号绑给某个 worker project。"
                "如果 reviewers 在这里就配齐了，project_set 时可以传空 [] 继承全局。"
            ),
        }

    return StructuredTool.from_function(
        coroutine=_run,
        name="clawbot_login_confirm",
        description=(
            "（Builder 专用）阻塞等待用户扫码完成，扫完把微信账号入库。"
            "参数：qrcode_session（来自 clawbot_login_start）、name（用户起的账号名，全局唯一）、"
            "description（可选）、reviewers（WeChat user_id 列表，可空）、max_poll_seconds(默认240)。"
            "成功返回 clawbot_account_id。"
        ),
    )


def list_clawbot_accounts_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _run() -> dict:
        from app.models.approvals import WechatClawbotAccount
        from sqlalchemy import select

        if ctx.db_factory is None:
            return {"ok": False, "error": "db_factory not available"}
        async with ctx.db_factory() as db:
            rows = (
                await db.execute(
                    select(WechatClawbotAccount).order_by(WechatClawbotAccount.created_at.desc())
                )
            ).scalars().all()
            items = [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "description": r.description,
                    "ilink_bot_id": r.ilink_bot_id,
                    "reviewers": list(r.reviewers or []),
                    "is_enabled": r.is_enabled,
                    "last_polled_at": r.last_polled_at.isoformat() if r.last_polled_at else None,
                    "last_error": r.last_error,
                }
                for r in rows
            ]
            return {"ok": True, "items": items, "total": len(items)}

    return StructuredTool.from_function(
        coroutine=_run,
        name="list_clawbot_accounts",
        description=(
            "（Builder 专用）列所有已绑定的微信 Clawbot 账号，看哪个能复用给当前项目。"
            "无参数。"
        ),
    )


def mission_set_approval_channel_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _run(
        target_project_id: str,
        clawbot_account_id: str,
        reviewer_wechat_ids: list[str] | None = None,
        enabled: bool = True,
    ) -> dict:
        """把项目与微信 Clawbot 账号关联，并设定该项目的审批人列表（空表则继承账号默认）。"""
        from app.models.approvals import (
            MissionApprovalChannel,
            WechatClawbotAccount,
        )
        from app.services import mission_service
        from sqlalchemy import select

        if ctx.db_factory is None:
            return {"ok": False, "error": "db_factory not available"}
        async with ctx.db_factory() as db:
            pid = await mission_service.resolve_mission_id(db, target_project_id)
            if pid is None:
                return {"ok": False, "error": f"target_project_id={target_project_id!r} 不是合法 UUID 或 slug"}
            try:
                aid = uuid.UUID(clawbot_account_id)
            except (ValueError, TypeError):
                return {"ok": False, "error": f"clawbot_account_id={clawbot_account_id!r} 不是合法 UUID"}
            acc = await db.get(WechatClawbotAccount, aid)
            if acc is None:
                return {"ok": False, "error": "clawbot_account 不存在"}

            row = (
                await db.execute(
                    select(MissionApprovalChannel).where(
                        MissionApprovalChannel.mission_id == pid
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = MissionApprovalChannel(
                    mission_id=pid,
                    clawbot_account_id=aid,
                    reviewer_wechat_ids=list(reviewer_wechat_ids or []),
                    enabled=enabled,
                )
                db.add(row)
            else:
                row.clawbot_account_id = aid
                row.reviewer_wechat_ids = list(reviewer_wechat_ids or [])
                row.enabled = enabled
            await db.commit()
            await db.refresh(row)
            effective_reviewers = (
                list(row.reviewer_wechat_ids or []) or list(acc.reviewers or [])
            )
            return {
                "ok": True,
                "mission_id": str(pid),
                "clawbot_account_id": str(aid),
                "enabled": row.enabled,
                "effective_reviewers": effective_reviewers,
                "note": (
                    f"以后该项目里 request_approval 会同步发到这 "
                    f"{len(effective_reviewers)} 个 WeChat 用户。"
                ),
            }

    return StructuredTool.from_function(
        coroutine=_run,
        name="mission_set_approval_channel",
        description=(
            "（Builder 专用）配置 worker project 的审批渠道：绑微信 Clawbot 账号 + 指定项目审批人。"
            "参数：target_project_id(UUID 或 slug) / clawbot_account_id(UUID) / "
            "reviewer_wechat_ids(WeChat user_id 列表，可空=继承账号默认) / enabled(默认 true)。"
        ),
    )


__all__ = (
    "clawbot_login_start_tool",
    "clawbot_login_confirm_tool",
    "list_clawbot_accounts_tool",
    "mission_set_approval_channel_tool",
)
