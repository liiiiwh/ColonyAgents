"""cand① 自优化闭环 · 决策状态机（纯函数）。

把 L2 自调优从「等 super 在 protocol 里手写循环」改成代码驱动闭环的判定核心：
给定信号快照 → 决定下一动作。自动应用 + 自动评估 + 自动回滚（配额内，自纠错）。

- 有待评估改动时：样本不足→WAIT；够样本且通过率守住→KEEP；回退→REVERT（优先评估，不叠新提案）。
- 无待评估：有回归且配额内→PROPOSE；否则 NONE。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OptAction(str, Enum):
    NONE = "none"
    PROPOSE = "propose"   # 检测到回归 → 让对应 agent 提一版修复（LLM 一次聚焦调用）
    WAIT = "wait"         # 已 apply，样本不足，等够再评
    KEEP = "keep"         # 评估：改动守住 → 保留
    REVERT = "revert"     # 评估：改动变差 → 回滚


@dataclass
class OptState:
    has_pending_change: bool      # 有一版已 apply、待评估的改动
    samples_since_apply: int      # apply 以来累计的评估样本（quality_gate verdict 数）
    eval_threshold: int           # 评估所需最小样本
    current_pass_rate: float      # 当前 quality_gate 通过率
    baseline_pass_rate: float     # apply 时的 baseline 通过率
    tolerance: float              # 允许的下滑容差（如 0.1）
    regression: bool              # 双信号（通过率/telemetry）当前是否在报回归
    quota_remaining: int          # 24h apply 配额剩余


def decide_optimization_action(s: OptState) -> tuple[OptAction, str]:
    # 1) 有待评估改动 → 先评估，绝不叠新提案
    if s.has_pending_change:
        if s.samples_since_apply < s.eval_threshold:
            return OptAction.WAIT, f"样本不足（{s.samples_since_apply}/{s.eval_threshold}），等够再评"
        floor = s.baseline_pass_rate - s.tolerance
        if s.current_pass_rate >= floor:
            return OptAction.KEEP, f"通过率守住（{s.current_pass_rate:.2f} ≥ {floor:.2f}），保留改动"
        return OptAction.REVERT, f"通过率回退（{s.current_pass_rate:.2f} < {floor:.2f}），自动回滚"

    # 2) 无待评估 → 有回归且配额内才提案
    if s.regression:
        if s.quota_remaining > 0:
            return OptAction.PROPOSE, "检测到回归，配额内提一版修复"
        return OptAction.NONE, "回归但 24h 配额耗尽，等下个周期"
    return OptAction.NONE, "无回归、无待评估，免动"


@dataclass
class RegressionMetrics:
    """双信号快照：quality_gate 通过率 + worker telemetry。"""
    pass_rate: float | None          # quality_gate 通过率（None=无数据）
    pass_rate_floor: float
    success_rate: float | None       # worker telemetry 成功率（None=无数据）
    success_rate_floor: float
    top_repeated_error: int          # 单一错误重复次数
    repeated_error_floor: int        # ≥ 即判执行回归
    sample_count: int                # 可用样本数
    min_samples: int                 # 少于此不判（防噪声触发自优化）


def detect_regression(m: RegressionMetrics) -> tuple[bool, str]:
    """双信号→是否回归。样本不足一律不判，避免噪声驱动 LLM 提案浪费 token。"""
    if m.sample_count < m.min_samples:
        return False, f"样本不足（{m.sample_count}/{m.min_samples}），不判回归"
    reasons: list[str] = []
    if m.pass_rate is not None and m.pass_rate < m.pass_rate_floor:
        reasons.append(f"质量门通过率 {m.pass_rate:.2f} < {m.pass_rate_floor:.2f}")
    if m.success_rate is not None and m.success_rate < m.success_rate_floor:
        reasons.append(f"worker 成功率 {m.success_rate:.2f} < {m.success_rate_floor:.2f}")
    if m.top_repeated_error >= m.repeated_error_floor:
        reasons.append(f"同一错误重复 {m.top_repeated_error} ≥ {m.repeated_error_floor} 次")
    if reasons:
        return True, "；".join(reasons)
    return False, "双信号正常"


async def run_optimization_cycle(state: "OptState", actions) -> tuple["OptAction", str]:
    """决策 → 派发到对应 L2 动作（actions 注入便于独测，真实版接 L2 propose/apply/revert）。

    actions 需提供 async propose() / keep() / revert()（WAIT/NONE 不动）。返回 (动作, 理由)。
    """
    act, reason = decide_optimization_action(state)
    if act is OptAction.PROPOSE:
        await actions.propose(reason)
    elif act is OptAction.KEEP:
        await actions.keep(reason)
    elif act is OptAction.REVERT:
        await actions.revert(reason)
    return act, reason
