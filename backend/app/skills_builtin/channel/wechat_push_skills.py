"""微信主动推送 skill —— 区别于 request_approval：不写 pending_approvals 表，
只是把一段消息推给配置好的微信审批人/通知人。

业务场景：
- 数据日报 / 周报 / 实时告警
- daemon 跑完一轮的简要总结
- 错误通知

调用方需要事先通过 Builder 给 project 配 `approval_channel`（共享 reviewer 列表），
或者显式传 `target_wechat_ids`。失败时把发送任务塞 outbox（last_error），不阻塞 worker。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langchain_core.tools import StructuredTool

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


def wechat_push_notification_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _run(
        message: str,
        title: str = "",
        target_wechat_ids: list[str] | None = None,
    ) -> dict:
        """主动推送一段消息到微信审批人（纯通知，不创建审批请求）。

        Args:
            message: 推送内容（markdown 文本）
            title: 顶部加粗标题（可选）
            target_wechat_ids: 自定义目标 WeChat user_id 列表；为空则用项目绑定的 reviewers
        """
        from sqlalchemy import select

        from app.core.encryption import decrypt
        from app.models.approvals import (
            MissionApprovalChannel,
            WechatClawbotAccount,
        )
        from app.services import wechat_clawbot

        if ctx.db_factory is None:
            return {"ok": False, "error": "db_factory not available"}
        if ctx.mission_id is None:
            return {"ok": False, "error": "mission_id 缺失（worker daemon 必带）"}
        if not (message or "").strip():
            return {"ok": False, "error": "message 不能为空"}

        async with ctx.db_factory() as db:
            cfg = (
                await db.execute(
                    select(MissionApprovalChannel).where(
                        MissionApprovalChannel.mission_id == ctx.mission_id
                    )
                )
            ).scalar_one_or_none()
            if cfg is None or not cfg.enabled or cfg.clawbot_account_id is None:
                return {
                    "ok": False,
                    "error": "项目未配置 WeChat 通知渠道。先在 admin/clawbot 绑账号 + 用 mission_set_approval_channel 关联",
                }
            acc = await db.get(WechatClawbotAccount, cfg.clawbot_account_id)
            if acc is None or not acc.is_enabled:
                return {"ok": False, "error": "对应 clawbot 账号不存在或已禁用"}

            recipients = list(target_wechat_ids or []) or (
                list(cfg.reviewer_wechat_ids or []) or list(acc.reviewers or [])
            )
            if not recipients:
                return {"ok": False, "error": "没有目标接收人（reviewer 列表为空）"}

            body = (f"🔔 **{title.strip()}**\n\n" if title.strip() else "") + message.strip()
            token = decrypt(acc.bot_token)
            ctx_tokens = dict(acc.context_tokens or {})

            sent: list[str] = []
            failed: list[dict] = []
            for uid in recipients:
                try:
                    await wechat_clawbot.send_text(
                        token=token,
                        base_url=acc.base_url,
                        to_user_id=uid,
                        text=body,
                        context_token=str(ctx_tokens.get(uid, "")),
                    )
                    sent.append(uid)
                except Exception as exc:  # noqa: BLE001
                    failed.append({"user_id": uid, "error": str(exc)})
                    logger.warning(
                        "[wechat_push] 用户 %s 推送失败（首次未对话过 bot？）: %s",
                        uid, exc,
                    )

            # 失败的塞 outbox（下次该 user 主动发消息时 poller 会 flush）
            if failed:
                from app.services import wechat_outbox
                await wechat_outbox.queue(
                    db, account_id=acc.id, mission_id=ctx.mission_id,
                    failed_recipients=failed, content=body,
                    kind="notification",
                )

        return {
            "ok": True,
            "sent_count": len(sent),
            "sent_to": sent,
            "queued_for_first_contact": [f["user_id"] for f in failed],
            "note": (
                "首次未跟 bot 对话过的用户会收到推送失败 → 已塞 outbox，等他们主动给 bot 发"
                "任意消息触发自动 flush；同时 admin/clawbot 页会显示该 outbox。"
                if failed else "全部推送成功"
            ),
        }

    return StructuredTool.from_function(
        coroutine=_run,
        name="wechat_push_notification",
        description=(
            "主动推送一段消息到项目绑定的微信审批人（**纯通知，不是审批请求**）。"
            "用于数据日报、运行总结、告警通知等。"
            "**前提**：项目已通过 mission_set_approval_channel 绑定 clawbot 账号。"
            "参数：message(str 必填) / title(str 可选) / target_wechat_ids(list 可选，覆盖默认)。"
        ),
    )


__all__ = ("wechat_push_notification_tool",)
