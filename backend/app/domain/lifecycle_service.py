"""v6 · LifecycleService —— Mission lifecycle 写入单一 seam。

设计意图（CONTEXT.md > "Lifecycle 状态机"）：
- 所有 lifecycle 写入路径只能过本服务，外部不再裸 UPDATE
- 跑 FSM 校验（非法 transition 抛 InvalidLifecycleTransition）
- 持有 SELECT FOR UPDATE 行锁，防并发跑偏
- 写 DB + 推 event_bus + （可选）写 agent_activities 留证
- v3 老字段 runtime_status 作 derived view 自动跟着同步

测试入口在 tests/test_v6_lifecycle_service.py。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, UTC

from sqlalchemy import text as _sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.lifecycle import (
    Lifecycle,
    LifecycleAction,
    InvalidLifecycleTransition,
    transition as _pure_transition,
    is_alive,
)

logger = logging.getLogger(__name__)


class LifecycleService:
    """Mission 级 lifecycle 状态管理。

    用法：
        await LifecycleService(db).transition(
            mission_id, LifecycleAction.PAUSE_FOR_CAPABILITY,
            reason="缺 xhs_ops",
        )
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def transition(
        self,
        mission_id: uuid.UUID,
        action: LifecycleAction,
        *,
        reason: str | None = None,
        force: bool = False,
    ) -> Lifecycle:
        """跑 FSM transition + 写 DB + 推事件。

        force=True 走 admin override（跳过 FSM 校验，直接写）—— 仅给 admin
        排障用，UI 上要红色 banner 标识。
        """
        # 用 ORM 取 + 写：跨 PG/sqlite 兼容；PG 上额外加 FOR UPDATE 行锁
        from app.models.mission import Mission
        is_sqlite = self._db.bind and self._db.bind.dialect.name == "sqlite"
        if not is_sqlite:
            # PG 行锁（避免并发 chat / scheduler / admin 同时改）
            await self._db.execute(_sql_text(
                "SELECT 1 FROM missions WHERE id = :pid FOR UPDATE"
            ), {"pid": str(mission_id)})
        proj = await self._db.get(Mission, mission_id)
        if proj is None:
            raise ValueError(f"project {mission_id} 不存在")
        current_raw = proj.lifecycle_status or "stopped"
        try:
            current = Lifecycle(current_raw)
        except ValueError:
            current = Lifecycle.STOPPED  # 容错：DB 里出现非法值，按 stopped 处理

        if force:
            # 直接定到 action 的 nominal target；若 action 是 STOP → STOPPED
            target = _force_target(action)
        else:
            try:
                target = _pure_transition(current, action)
            except InvalidLifecycleTransition:
                logger.warning(
                    "[lifecycle] illegal transition project=%s %s --%s--> ?",
                    mission_id, current.value, action.value,
                )
                raise

        # paused_reason 仅在 paused_* 写；其它 transition 清空
        paused_reason = reason if target in (
            Lifecycle.PAUSED_WAITING_CAPABILITY,
            Lifecycle.PAUSED_CLARIFICATION,
        ) else None

        # v3 runtime_status 同步：is_alive=True → running；否则跟 lifecycle
        runtime = "running" if is_alive(target) and target != Lifecycle.STOPPING else (
            "stopped" if target == Lifecycle.STOPPED
            else "error" if target == Lifecycle.ERROR
            else target.value
        )

        proj.lifecycle_status = target.value
        proj.runtime_status = runtime
        proj.paused_reason = paused_reason
        await self._db.commit()
        await self._db.refresh(proj)

        logger.info(
            "[lifecycle] project=%s %s --%s--> %s (reason=%s force=%s)",
            mission_id, current.value, action.value, target.value, reason, force,
        )

        # publish event_bus (best-effort) — ADR-018 step 3b · channel = Mission (mission_id)
        try:
            from app.services.event_bus import bus as _bus
            await _bus.publish(mission_id, {
                "type": "lifecycle_changed",
                "from": current.value,
                "to": target.value,
                "action": action.value,
                "reason": reason,
                "at": datetime.now(UTC).isoformat(),
            })
        except Exception:
            logger.exception("[lifecycle] event_bus publish failed (不阻塞)")

        # V7.4 · 不再写 agent_activities（ADR-007 退役）。lifecycle 变更已 publish event_bus +
        # 落 chat 消息观测；transition 证据走 logger.info（上面已记）。
        return target


def _force_target(action: LifecycleAction) -> Lifecycle:
    """admin force 模式：按 action 名字反推合理目标。"""
    if action in (LifecycleAction.STOP,):
        return Lifecycle.STOPPED
    if action in (LifecycleAction.START, LifecycleAction.RESTART, LifecycleAction.RESUME):
        return Lifecycle.RUNNING
    if action == LifecycleAction.EXCEPTION:
        return Lifecycle.ERROR
    if action == LifecycleAction.PAUSE_FOR_CAPABILITY:
        return Lifecycle.PAUSED_WAITING_CAPABILITY
    if action == LifecycleAction.PAUSE_FOR_CLARIFICATION:
        return Lifecycle.PAUSED_CLARIFICATION
    if action == LifecycleAction.PAUSE_IDLE:
        return Lifecycle.PAUSED_IDLE
    if action == LifecycleAction.RESOLVE_CLARIFICATION:
        return Lifecycle.RUNNING
    return Lifecycle.STOPPED
