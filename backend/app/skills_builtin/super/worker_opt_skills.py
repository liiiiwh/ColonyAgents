"""ADR-025 D2 · Colony Worker Optimization super 的 work-order 自驱续跑/收尾技能。

work-order mission 全自动跑到完成：每轮结束时——
- 未完成且没弹 force_human 卡 → 调 `optimization_continue` 入队续跑（低延迟主路径）；
- 完成 → 调 `optimization_done` 软关闭（归档 + 按 capability 唤醒等待者 + 注销调度）。

两者按 kind 绑给所有 super，但服务层自守卫：只对 work-order mission（带 workflow_config.work_order）
生效，普通 super 误调无效——防误关自己 mission。漏调由兜底调度补踢、max-tick 强制收尾。
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import StructuredTool

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


def optimization_continue_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _continue() -> str:
        """（work-order）当前 worker 优化未完成时调：入队一条续跑指令，下一 tick 继续推进。

        守卫：有未决 force_human 审批卡 → 拒绝入队（不越过人工门）；非 work-order mission → 无效。"""
        if ctx.db_factory is None or ctx.mission_id is None:
            return json.dumps({"ok": False, "error": "缺上下文"})
        from app.services import worker_optimization_service as _wos

        async with ctx.db_factory() as db:
            res = await _wos.enqueue_continue(db, ctx.mission_id)
        return json.dumps({"ok": bool(res.get("enqueued")), **res}, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_continue,
        name="optimization_continue",
        description=(
            "（work-order）当前 worker 优化未完成、且本轮没弹 force_human 审批卡时调：入队续跑指令，"
            "daemon 下一 tick 继续。有未决人工审批卡则拒绝（不越人工门）；非 work-order mission 无效。"
        ),
    )


def optimization_done_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _done(summary: str = "", outcome: str = "fixed") -> str:
        """（work-order）当前 worker 优化完成时调：软关闭本 mission（归档）+ 按 capability 唤醒所有
        因 worker_issue:<cap> 停工的上报方 + 注销兜底调度。

        outcome ∈ fixed（已修）/ not_fixable（归因外部不可修）。非 work-order mission 无效（自守卫）。"""
        if ctx.db_factory is None or ctx.mission_id is None:
            return json.dumps({"ok": False, "error": "缺上下文"})
        from app.services import worker_optimization_service as _wos

        _outcome = outcome if outcome in ("fixed", "not_fixable") else "fixed"
        async with ctx.db_factory() as db:
            res = await _wos.close_work_order(db, ctx.mission_id, outcome=_outcome)
        return json.dumps(res, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_done,
        name="optimization_done",
        description=(
            "（work-order）当前 worker 优化完成时调：软关闭本 mission + 按 capability 唤醒等待者 + "
            "注销调度。参数 summary(str 收尾摘要) / outcome('fixed'|'not_fixable')。非 work-order 无效。"
        ),
    )
