"""平台 worker 健康体检（纯函数）· ADR-015 自检自迭代第一段。

确定性体检：给定每个 worker 从 `worker_invocation_log` 聚合出的指标，复用孤立的
`decide.py:detect_regression` 双信号判定，筛出「需要 LLM 介入迭代」的候选。

设计原则（防能力退化）：
- 样本不足一律不判（min_samples）——避免噪声驱动 LLM 浪费 token。
- 只挑**明显退化**（成功率低于地板 / 同一错误高频重复），不挑轻微抖动。
- 纯函数：体检逻辑可独测；真实数据由 service 层查 DB 拼装喂入。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.optimization.decide import RegressionMetrics, detect_regression


@dataclass
class WorkerHealthInput:
    worker_id: str
    name: str
    capability: str | None
    total: int                 # 窗口内总调用
    completed: int             # 成功数
    failed: int                # 失败数
    top_repeated_error_cnt: int  # 单一错误最高重复次数
    top_error_msg: str | None    # 该错误文本（给 LLM 诊断用）


@dataclass
class WorkerHealthThresholds:
    success_rate_floor: float = 0.75   # 成功率低于此 → 回归信号
    repeated_error_floor: int = 5      # 同一错误 ≥ 此次数 → 回归信号
    min_samples: int = 10              # 少于此不判（防噪声）


@dataclass
class WorkerHealthCandidate:
    worker_id: str
    name: str
    capability: str | None
    success_rate: float
    total: int
    reason: str                # 为何判为候选（人/LLM 可读）
    top_error_msg: str | None


def scan_worker_health(
    inputs: list[WorkerHealthInput],
    thresholds: WorkerHealthThresholds | None = None,
) -> list[WorkerHealthCandidate]:
    """返回需要迭代的 worker 候选（按成功率升序，最差的排前）。"""
    t = thresholds or WorkerHealthThresholds()
    candidates: list[WorkerHealthCandidate] = []
    for w in inputs:
        sr = (w.completed / w.total) if w.total > 0 else None
        m = RegressionMetrics(
            pass_rate=None,                 # 健康体检只用 telemetry 信号（无 project 质量门上下文）
            pass_rate_floor=0.0,
            success_rate=sr,
            success_rate_floor=t.success_rate_floor,
            top_repeated_error=w.top_repeated_error_cnt,
            repeated_error_floor=t.repeated_error_floor,
            sample_count=w.total,
            min_samples=t.min_samples,
        )
        regressed, reason = detect_regression(m)
        if regressed:
            candidates.append(WorkerHealthCandidate(
                worker_id=w.worker_id,
                name=w.name,
                capability=w.capability,
                success_rate=sr if sr is not None else 0.0,
                total=w.total,
                reason=reason,
                top_error_msg=w.top_error_msg,
            ))
    candidates.sort(key=lambda c: c.success_rate)
    return candidates
