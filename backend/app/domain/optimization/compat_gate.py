"""跨调用方兼容门（纯函数）· ADR-015 行为层兼容。

病根：L2 自调优把 worker `protocol_md` 改了之后，只用**触发迭代的那个 project** 的质量门
通过率做回归门。但 worker 是**全局共享单行**——别的 super（不同 action 组合）拿到改后的
worker 从没被校验。于是「项目 A 迭代 → 项目 B 被悄悄改坏」。

解法：把回归门从单项目升级为**全调用方**。从 `worker_invocation_log` 取该 worker 的
`(super_agent_id, action)` 分布与各自成功率，迭代前后对比：**任一调用方明显退化 → 判不兼容**。

门要松（防能力退化）：
- 样本不足的调用方跳过（不足以判定，不拦改进）。
- 只在**成功率下滑超过容差**时判退化（不是任何抖动）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CallerStat:
    """某调用方对该 worker 某 action 的成功率快照。"""
    super_agent_id: str
    action: str
    total: int
    completed: int

    @property
    def success_rate(self) -> float | None:
        return (self.completed / self.total) if self.total > 0 else None


@dataclass
class CompatVerdict:
    compatible: bool
    regressed_callers: list[str]   # "super:action" 列表
    reason: str


def check_cross_caller_compat(
    before: list[CallerStat],
    after: list[CallerStat],
    tolerance: float = 0.1,
    min_samples: int = 5,
) -> CompatVerdict:
    """迭代前后逐 (调用方, action) 比成功率；任一在足够样本下跌破容差 → 不兼容。"""
    before_map = {(s.super_agent_id, s.action): s for s in before}
    regressed: list[str] = []
    details: list[str] = []
    for a in after:
        key = (a.super_agent_id, a.action)
        b = before_map.get(key)
        if b is None:
            continue  # 新出现的调用方/action，无 before 基线，不判退化
        if a.total < min_samples or b.total < min_samples:
            continue  # 样本不足，不足以判定（不拦改进）
        b_sr, a_sr = b.success_rate, a.success_rate
        if b_sr is None or a_sr is None:
            continue
        if a_sr < b_sr - tolerance:
            label = f"{a.super_agent_id[:8]}:{a.action}"
            regressed.append(label)
            details.append(f"{label} 成功率 {b_sr:.2f}→{a_sr:.2f}")
    if regressed:
        return CompatVerdict(False, regressed, "调用方退化：" + "；".join(details))
    return CompatVerdict(True, [], "全部调用方未见明显退化")
