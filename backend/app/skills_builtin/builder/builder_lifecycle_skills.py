"""Builder Chat 专用 skills（DESIGN_WORKER 模式收尾用）。

- resume_super_agent：Builder 完成 worker 创建 / 升级后唤醒等待中的 super
- validate_backward_compat：升级现有 worker 前 dry-run 兼容校验（R9 强约束）
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from langchain_core.tools import StructuredTool

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


def resume_super_agent_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _resume(
        super_agent_id: str,
        capability_satisfied_by_agent_id: str = "",
        notes: str = "",
    ) -> str:
        """Builder Chat 在完成 worker 创建 / 升级后调，唤醒等待中的 super。

        - 将 super 的 project.lifecycle_status 从 paused_waiting_capability → running
        - 立即触发 1 次 super tick（同步），失败标 error + wechat 通知 user
        - 同时 dismiss 对应 escalation（capability_missing 类）

        实现：scan projects table 找 supervisor_agent_id == super_agent_id 的 project。
        """
        from sqlalchemy import select, update as _sql_update
        from app.models.mission import Mission, MissionEscalation
        from app.services import mission_daemon

        if ctx.db_factory is None:
            return json.dumps({"ok": False, "error": "缺 db_factory"})
        try:
            sup_uuid = uuid.UUID(super_agent_id)
        except (ValueError, TypeError):
            return json.dumps({"ok": False, "error": f"super_agent_id 不是 UUID: {super_agent_id}"})

        async with ctx.db_factory() as db:
            proj = (await db.execute(select(Mission).where(Mission.supervisor_agent_id == sup_uuid).limit(1))).scalar_one_or_none()
            if proj is None:
                return json.dumps({"ok": False, "error": f"找不到 super_agent_id={super_agent_id} 关联的 project"})
            old_status = proj.lifecycle_status
            old_reason = proj.paused_reason
            # v6 · 走 LifecycleService 单一入口
            try:
                from app.domain.lifecycle_service import LifecycleService
                from app.domain.lifecycle import LifecycleAction
                await LifecycleService(db).transition(
                    proj.id, LifecycleAction.RESUME, force=True,  # force：兼容 RESTART/RESUME 各种当前态
                )
                await db.refresh(proj)
            except Exception:
                # 兜底：旧路径
                proj.lifecycle_status = "running"
                proj.paused_reason = None
                if proj.runtime_status != "running":
                    proj.runtime_status = "running"
            # close pending escalations of capability_missing kind
            # 用 ORM update（Python 侧时间戳）保持 PG/sqlite 跨库可移植；不再裸 SQL now()。
            try:
                await db.execute(
                    _sql_update(MissionEscalation)
                    .where(
                        MissionEscalation.mission_id == proj.id,
                        MissionEscalation.status.in_(("pending", "delivered")),
                        MissionEscalation.category.in_(("structural", "worker_health")),
                    )
                    .values(
                        status="acted",
                        resolution_summary=(notes or "Builder resolved by adding/upgrading capability")[:1000],
                        resolved_at=datetime.now(UTC),
                        resolved_by=str(ctx.mission_id) if ctx.mission_id else "builder",
                    )
                )
            except Exception:
                logger.exception("[resume_super_agent] close escalations failed (不阻塞)")
            await db.commit()
            pid = proj.id

        # 立即触发一次 super tick
        try:
            async with ctx.db_factory() as db2:
                res = await mission_daemon.run_once(
                    db2, pid,
                    payload={"trigger": "manual", "user_message": f"[resume] {notes or 'Builder 完成 worker 处理，可继续'}"}
                )
            logger.info(
                "📊 colony_v3_resume project=%s super=%s old_status=%s tick_ok=%s",
                pid, super_agent_id, old_status, res.get("ok"),
            )
            return json.dumps({
                "ok": True,
                "super_agent_id": super_agent_id,
                "mission_id": str(pid),
                "previous_status": old_status,
                "previous_paused_reason": old_reason,
                "first_tick_result": res,
            }, ensure_ascii=False)
        except Exception as exc:
            logger.exception("[resume_super_agent] first tick failed")
            return json.dumps({
                "ok": True,
                "super_agent_id": super_agent_id,
                "mission_id": str(pid),
                "previous_status": old_status,
                "warning": f"恢复 lifecycle 成功但首 tick 失败：{exc}",
            }, ensure_ascii=False)
    return StructuredTool.from_function(
        coroutine=_resume,
        name="resume_super_agent",
        description=(
            "（Builder-only v3）Builder Chat 完成 worker 创建 / 升级 后调，唤醒 paused super。"
            "把 project.lifecycle_status 切回 running + 立即跑一次 tick + 关 pending escalation。"
        ),
    )


def validate_backward_compat_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _validate(
        worker_agent_id: str,
        proposed_capability_contract: dict,
    ) -> str:
        """R9 向下兼容 dry-run 校验。比对 现有 capability_contract.advertises 与 proposed：
        - 旧 action 必须在新里出现（不允许删；只允许加 deprecated_actions）
        - 旧 input_schema 字段不允许新增 required（只允许加 optional）
        - 旧 output_schema 字段不允许删除（只允许加）

        返回 {compatible: bool, violations: [...], warnings: [...]}
        """
        from app.models.agent import Agent

        if ctx.db_factory is None:
            return json.dumps({"compatible": False, "error": "缺 db_factory"})
        try:
            wid = uuid.UUID(worker_agent_id)
        except (ValueError, TypeError):
            return json.dumps({"compatible": False, "error": "worker_agent_id 不是 UUID"})
        async with ctx.db_factory() as db:
            agent = await db.get(Agent, wid)
            if agent is None:
                return json.dumps({"compatible": False, "error": "agent 不存在"})
            old = (agent.extra_config or {}).get("capability_contract") or {}
        # ADR-008 P5 · 复用纯核 check_backward_compat（工厂硬门也用同一个，避免漂移）
        from app.domain.builder.spec_validation import check_backward_compat
        result = check_backward_compat(old, proposed_capability_contract)
        logger.info(
            "📊 colony_v3_backward_compat worker=%s compatible=%s violations=%d warnings=%d",
            worker_agent_id, result["compatible"], len(result["violations"]), len(result["warnings"]),
        )
        return json.dumps(result, ensure_ascii=False)
    return StructuredTool.from_function(
        coroutine=_validate,
        name="validate_backward_compat",
        description=(
            "（Builder-only v3）升级现有 worker 前 dry-run R9 向下兼容校验。"
            "返回 {compatible, violations, warnings}；violations 非空表示有破坏，不允许 promote。"
        ),
    )
