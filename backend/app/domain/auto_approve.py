"""auto_approve 选项选择（纯函数）。

病根：auto_approve 盲取 options[0]，假设"第一个=同意/推进"。但选项由 super 的 LLM 自由生成，
顺序无约束——一旦把"取消/放弃"放第一个，自动授权就点错（卡死或白跑）。

解法：挑**语义上的"肯定/推进"项**（就这么干/同意/继续/发布…），分不出肯定项才回退 options[0]
（沿用 propose-confirm「推进项放第一」约定）。这样无论选项怎么排，auto 都稳定往前走。
"""
from __future__ import annotations

# 肯定/推进类关键词（命中=想往前走）
_AFFIRM = (
    "就这么干", "同意", "确认", "批准", "通过", "继续", "执行", "发布", "开始",
    "好的", "可以", "是", "确定", "用这个", "就这样", "马上", "立即", "现在",
    "approve", "yes", "ok", "go", "proceed", "confirm",
)
# 否定/保守/放弃类关键词（命中=别动/退回）
_NEGATIVE = (
    "取消", "拒绝", "放弃", "暂不", "先不", "不要", "稍后", "等我", "保留", "先别",
    "驳回", "撤销", "中止", "停止", "不发", "再想想", "我要调整", "我自己说",
    "cancel", "no", "reject", "skip", "stop", "abort", "later",
)


def resolve_auto_approve(
    *,
    must_human: bool,
    ctx_force_auto: bool,
    project_auto_approve: bool,
) -> bool:
    """request_approval 是否自动通过。优先级：must_human > ctx 强制 auto > 项目 auto_approve。

    ADR-028 D1（修订）· `must_human` 由 **approval_judge 唯一裁决**（request_approval 服务端
    自动咨询，不再由 super 传 force_human）。
    - must_human=True → **永远 False**（人工门硬停点）：无视 ctx_force_auto 与 project_auto_approve
      的任何组合——即使 mission.auto_approve=True 也硬停等真人（落卡 + cancel 当前 tick 由 D4 接线）。
    - ctx_force_auto=True（系统级后台会话，如平台 Worker 健康自检，无人盯卡片）→ True。
    - 否则回落项目 auto_approve 设置。
    """
    if must_human:
        return False  # ADR-028 D1 硬停点：must_human 凌驾一切 auto 信号
    if ctx_force_auto:
        return True
    return bool(project_auto_approve)


def _score(option: str) -> int:
    o = (option or "").lower()
    s = 0
    if any(k in o for k in _AFFIRM):
        s += 2
    if any(k in o for k in _NEGATIVE):
        s -= 3  # 否定权重更高：宁可不把"取消"当推进项
    return s


def pick_auto_option(options: list[str] | None) -> str:
    """auto_approve 时选哪个选项：优先最"肯定/推进"的；无明确肯定项则回退 options[0]。"""
    if not options:
        return "同意"
    scored = [(_score(o), i, o) for i, o in enumerate(options)]
    # 最高分；同分取最靠前（沿用"推进项放前"约定）
    best_score, _idx, best_opt = max(scored, key=lambda x: (x[0], -x[1]))
    if best_score > 0:
        return best_opt
    # 没有任何明确肯定项（如纯多选「方案A/方案B」，或全是中性词）→ 回退 options[0]
    return options[0]
