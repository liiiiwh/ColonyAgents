"""Pending Approval REST API（observe 页 / Builder skill / 微信回调都走这层）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.core.deps import AdminUser, DBSession
from app.services import pending_approval_service

router = APIRouter(prefix="/api", tags=["pending-approvals"])


class PendingApprovalPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mission_id: uuid.UUID
    request_id: str
    thread_key: str | None = None
    agent_node_name: str | None
    title: str
    message: str
    options: list[str]
    status: str
    decided_option: str | None
    decided_by: str | None
    decided_at: datetime | None
    clawbot_account_id: uuid.UUID | None
    clawbot_user_ids: list[str] | None
    clawbot_sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DecideBody(BaseModel):
    option: str
    decided_by: str = "observe"


@router.get(
    "/missions/{mission_id}/pending-approvals",
    response_model=list[PendingApprovalPublic],
)
async def list_for_project(
    mission_id: uuid.UUID,
    _: AdminUser,
    db: DBSession,
    only_pending: bool = True,
) -> list[PendingApprovalPublic]:
    rows = await pending_approval_service.list_pending_for_project(
        db, mission_id, status="pending" if only_pending else None
    )
    return [PendingApprovalPublic.model_validate(r) for r in rows]


@router.post(
    "/pending-approvals/{request_id}/decide",
    response_model=PendingApprovalPublic,
)
async def decide_pending(
    request_id: str,
    body: DecideBody,
    _: AdminUser,
    db: DBSession,
) -> PendingApprovalPublic:
    if not body.option.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="option 不能为空")
    row = await pending_approval_service.decide(
        db,
        request_id=request_id,
        option=body.option.strip(),
        decided_by=(body.decided_by or "observe").strip(),
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="审批请求不存在")
    # v5 · 向 event_bus 推 approval_resolved；前端 inline 卡片立即翻转状态
    try:
        from app.services.event_bus import bus as _bus
        if row.mission_id:  # ADR-018 step 3b · channel = Mission (mission_id)
            await _bus.publish(row.mission_id, {
                "type": "approval_resolved",
                "request_id": str(row.request_id),
                "option": body.option.strip(),
                "decided_by": (body.decided_by or "observe").strip(),
                "via": "ui",
            })
    except Exception:
        pass  # 非阻塞
    return PendingApprovalPublic.model_validate(row)


@router.get(
    "/pending-approvals/{request_id}",
    response_model=PendingApprovalPublic,
)
async def get_pending(
    request_id: str,
    _: AdminUser,
    db: DBSession,
) -> PendingApprovalPublic:
    row = await pending_approval_service.get_by_request_id(db, request_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="审批请求不存在")
    return PendingApprovalPublic.model_validate(row)
