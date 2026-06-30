"""R2-1 · WorkerInvocation precheck · invoke_worker 前置校验纯函数。

从 super_dispatch_skills._invoke_worker_inner 374-LOC 巨函数前 60 行抽出来。
所有 invariant 校验（V17 嵌套 / V37 反问轮数 / 必需 super_id）汇总在这里，
纯函数 → 不需要 DB / LangChain / 网络，单元可测。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrecheckResult:
    """invoke_worker 前置校验结果。"""
    ok: bool
    error_msg: str | None = None

    def to_envelope(self) -> dict:
        """转成 invoke_worker 历史兼容的 envelope dict（status='failed' 表示拒绝）。"""
        if self.ok:
            return {"ok": True}
        return {
            "ok": False,
            "status": "failed",
            "error_msg": self.error_msg or "precheck failed",
        }


def precheck_invocation(
    *,
    call_stack: list[str],
    clarification_round: int,
    super_id: str | None,
    max_nesting: int,
    max_clarification_rounds: int,
) -> PrecheckResult:
    """v6 · 检查 invoke_worker 调用前置条件。"""
    # V17 嵌套深度（worker 不该再调）
    if len(call_stack) >= max_nesting:
        return PrecheckResult(
            ok=False,
            error_msg=f"❌ invoke_worker 嵌套深度超 {max_nesting}（V17）；当前栈={call_stack}",
        )
    # V37 反问轮数上限（worker → super clarification）
    if clarification_round >= max_clarification_rounds:
        return PrecheckResult(
            ok=False,
            error_msg=(
                f"❌ clarification 循环超 {max_clarification_rounds} 轮（V37）；"
                "请改用 request_approval 让 user 介入"
            ),
        )
    if not super_id:
        return PrecheckResult(
            ok=False,
            error_msg="❌ ctx.extra.agent_id（super）缺失",
        )
    return PrecheckResult(ok=True)
