"""R3-4 · ApprovalResolution · 批准决议后的分叉决策（纯）。

decide() 记录审批后要决定「接下来触发什么」：
- orchestrator session → 后台推进 supervisor 一轮
- daemon session + 肯定语义 → 直接派发 publisher worker（绕过 LLM 重生成）
- 其它 → 不动（等下次 tick / 用户）

把这个 scope×option 矩阵抽成纯函数；实际 asyncio.create_task 仍在 pending_approval_service。
新增 approval 模式 = 加一个 enum 分支，不再往 decide() 里塞 if-else。
"""
from __future__ import annotations

import enum


class PostDecisionAction(str, enum.Enum):
    NONE = "none"
    ADVANCE_ORCHESTRATOR = "advance_orchestrator"
    TRIGGER_TICK = "trigger_tick"  # ADR-008 D2 · daemon 审批回复统一触发 idle-tick


_AFFIRMATIVE_KEYWORDS = (
    "发布", "通过", "同意", "OK", "ok", "确认", "✓", "✅", "yes", "Yes", "YES",
)


def is_affirmative(option: str) -> bool:
    """approval 选项是否「通过/发布」语义。"""
    if not option:
        return False
    return any(k in option for k in _AFFIRMATIVE_KEYWORDS)


def build_auto_decide_option(chat_content: str) -> str:
    """R4-4 · 未审批时把用户 chat 原文当作审批意见（option），截断防爆。

    用户讲「调整 schedule 时间」「我要先配好 MCP」等自然语言 → 直接作为最旧 pending
    approval 的 decided_option，daemon 下次 tick 读 [approval_response] 自然按用户意见继续。
    """
    return (chat_content or "").strip()[:500]


def route_post_decision(*, scope: str, option: str) -> PostDecisionAction:
    """根据 session.scope 决定批准后动作。

    ADR-008 D2：daemon 审批回复统一触发 idle-tick（不再按 affirmative 分叉走 publisher
    fast-path）。super 读 [approval_response] 自行决定怎么继续（发布 / 改方案 / 放弃）。
    affirmative/非 affirmative 一视同仁。
    """
    if scope == "orchestrator":
        return PostDecisionAction.ADVANCE_ORCHESTRATOR
    if scope == "daemon":
        return PostDecisionAction.TRIGGER_TICK
    return PostDecisionAction.NONE
