"""微信 Clawbot 账号 CRUD + 扫码登录 + 项目审批渠道关联。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.core.deps import AdminUser, DBSession
from app.core.encryption import decrypt, encrypt
from app.models.approvals import (
    MissionApprovalChannel,
    WechatClawbotAccount,
)
from app.services import wechat_clawbot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["clawbot-accounts"])


# ─────────────────────────── schemas ───────────────────────────

class ClawbotAccountPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    base_url: str
    ilink_bot_id: str
    ilink_user_id: str | None
    reviewers: list[str]
    is_enabled: bool
    last_polled_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ClawbotAccountUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    reviewers: list[str] | None = None
    is_enabled: bool | None = None


class StartLoginResponse(BaseModel):
    qrcode_session: str
    qrcode_img_url: str
    qrcode_inline_img_url: str = ""


class ConfirmLoginBody(BaseModel):
    name: str
    description: str = ""
    reviewers: list[str] = []
    qrcode_session: str
    # 等用户扫码确认；服务端轮询最多 max_poll_seconds 秒
    max_poll_seconds: int = 240


class ChannelConfigBody(BaseModel):
    clawbot_account_id: uuid.UUID | None = None
    reviewer_wechat_ids: list[str] = []
    enabled: bool = True


class MissionChannelPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    mission_id: uuid.UUID
    clawbot_account_id: uuid.UUID | None
    reviewer_wechat_ids: list[str]
    enabled: bool


# ─────────────────────────── 账号 CRUD ───────────────────────────

@router.get("/clawbot-accounts", response_model=list[ClawbotAccountPublic])
async def list_accounts(_: AdminUser, db: DBSession) -> list[ClawbotAccountPublic]:
    rows = (
        await db.execute(
            select(WechatClawbotAccount).order_by(WechatClawbotAccount.created_at.desc())
        )
    ).scalars().all()
    return [ClawbotAccountPublic.model_validate(r) for r in rows]


@router.get("/clawbot-accounts/{acc_id}", response_model=ClawbotAccountPublic)
async def get_account(
    acc_id: uuid.UUID, _: AdminUser, db: DBSession
) -> ClawbotAccountPublic:
    row = await db.get(WechatClawbotAccount, acc_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="账号不存在")
    return ClawbotAccountPublic.model_validate(row)


@router.put("/clawbot-accounts/{acc_id}", response_model=ClawbotAccountPublic)
async def update_account(
    acc_id: uuid.UUID, body: ClawbotAccountUpdate, _: AdminUser, db: DBSession
) -> ClawbotAccountPublic:
    row = await db.get(WechatClawbotAccount, acc_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="账号不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return ClawbotAccountPublic.model_validate(row)


class OutboxItemPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    mission_id: uuid.UUID | None
    target_wechat_id: str
    kind: str
    content: str
    status: str
    attempt_count: int
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


@router.get("/clawbot-accounts/{acc_id}/outbox", response_model=list[OutboxItemPublic])
async def list_outbox(
    acc_id: uuid.UUID, _: AdminUser, db: DBSession
) -> list[OutboxItemPublic]:
    from app.services import wechat_outbox as _ob
    rows = await _ob.list_pending_for_account(db, acc_id)
    return [OutboxItemPublic.model_validate(r) for r in rows]


@router.delete("/clawbot-accounts/{acc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(acc_id: uuid.UUID, _: AdminUser, db: DBSession) -> None:
    row = await db.get(WechatClawbotAccount, acc_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="账号不存在")
    await db.delete(row)
    await db.commit()


# ─────────────────────────── 扫码登录 ───────────────────────────

@router.post("/clawbot-accounts/login/start", response_model=StartLoginResponse)
async def start_login(_: AdminUser) -> StartLoginResponse:
    """拉一个二维码 session。前端拿 qrcode_img_url 渲染让用户扫。"""
    out = await wechat_clawbot.get_qrcode()
    if not out.get("qrcode_session"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="ilink 服务返回空 qrcode_session")
    return StartLoginResponse(**out)


@router.post("/clawbot-accounts/login/confirm", response_model=ClawbotAccountPublic)
async def confirm_login(
    body: ConfirmLoginBody, user: AdminUser, db: DBSession
) -> ClawbotAccountPublic:
    """阻塞轮询直到扫码完成（or 超时），把凭证落库。

    前端在用户点过 'start_login' 后调这个，传 qrcode_session。
    用户扫码 + 微信里确认后立刻返回；过 max_poll_seconds 仍未确认就报 408。
    """
    if not body.name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="name 不能为空")

    # 检查重名
    existing = (
        await db.execute(
            select(WechatClawbotAccount).where(WechatClawbotAccount.name == body.name.strip())
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"账号 name={body.name!r} 已存在"
        )

    deadline = asyncio.get_event_loop().time() + max(30, min(body.max_poll_seconds, 480))
    confirmed: dict = {}
    while True:
        if asyncio.get_event_loop().time() > deadline:
            raise HTTPException(
                status.HTTP_408_REQUEST_TIMEOUT,
                detail="扫码超时；请重新 start_login 后立刻扫码确认",
            )
        try:
            res = await wechat_clawbot.poll_qrcode_status(body.qrcode_session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("poll_qrcode_status 异常 %s（继续重试）", exc)
            await asyncio.sleep(2)
            continue
        st = res.get("status")
        if st == "confirmed":
            confirmed = res
            break
        if st == "expired":
            raise HTTPException(
                status.HTTP_410_GONE,
                detail="二维码已过期，请重新 start_login 拿新二维码",
            )
        # wait / scaned：继续轮询
        await asyncio.sleep(1.5)

    bot_token = confirmed.get("bot_token") or ""
    base_url = confirmed.get("baseurl") or wechat_clawbot.ILINK_DEFAULT_BASE
    ilink_bot_id = confirmed.get("ilink_bot_id") or ""
    ilink_user_id = confirmed.get("ilink_user_id") or None
    if not bot_token or not ilink_bot_id:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"扫码成功但 ilink 返回字段缺失: {confirmed}",
        )

    acc = WechatClawbotAccount(
        name=body.name.strip(),
        description=body.description.strip(),
        bot_token=encrypt(bot_token),
        base_url=base_url,
        ilink_bot_id=ilink_bot_id,
        ilink_user_id=ilink_user_id,
        sync_buffer="",
        context_tokens={},
        reviewers=list(body.reviewers or []),
        is_enabled=True,
        created_by=user.id,
    )
    db.add(acc)
    await db.commit()
    await db.refresh(acc)
    logger.info("[clawbot] account=%s 登录入库", acc.name)

    # 立即起 poller，不用等下次重启
    try:
        from app.services import wechat_poller
        wechat_poller.start_for_account(acc.id)
    except Exception:  # noqa: BLE001
        logger.exception("[clawbot] start_for_account 失败")

    return ClawbotAccountPublic.model_validate(acc)


# ─────────────────────────── 项目审批渠道关联 ───────────────────────────

@router.get(
    "/missions/{mission_id}/approval-channel",
    response_model=MissionChannelPublic | None,
)
async def get_channel(
    mission_id: uuid.UUID, _: AdminUser, db: DBSession
) -> MissionChannelPublic | None:
    row = (
        await db.execute(
            select(MissionApprovalChannel).where(
                MissionApprovalChannel.mission_id == mission_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return MissionChannelPublic.model_validate(row)


@router.put(
    "/missions/{mission_id}/approval-channel",
    response_model=MissionChannelPublic,
)
async def upsert_channel(
    mission_id: uuid.UUID, body: ChannelConfigBody, _: AdminUser, db: DBSession
) -> MissionChannelPublic:
    row = (
        await db.execute(
            select(MissionApprovalChannel).where(
                MissionApprovalChannel.mission_id == mission_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = MissionApprovalChannel(
            mission_id=mission_id,
            clawbot_account_id=body.clawbot_account_id,
            reviewer_wechat_ids=list(body.reviewer_wechat_ids or []),
            enabled=body.enabled,
        )
        db.add(row)
    else:
        row.clawbot_account_id = body.clawbot_account_id
        row.reviewer_wechat_ids = list(body.reviewer_wechat_ids or [])
        row.enabled = body.enabled
    await db.commit()
    await db.refresh(row)
    return MissionChannelPublic.model_validate(row)


@router.delete(
    "/missions/{mission_id}/approval-channel",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_channel(
    mission_id: uuid.UUID, _: AdminUser, db: DBSession
) -> None:
    row = (
        await db.execute(
            select(MissionApprovalChannel).where(
                MissionApprovalChannel.mission_id == mission_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return
    await db.delete(row)
    await db.commit()


__all__ = ("router",)
