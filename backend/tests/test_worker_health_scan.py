"""worker 健康体检 + 跨调用方兼容门（ADR-015 自检自迭代纯核心）。"""
from app.domain.optimization.health_scan import (
    WorkerHealthInput, WorkerHealthThresholds, scan_worker_health,
)
from app.domain.optimization.compat_gate import CallerStat, check_cross_caller_compat


def _w(wid, total, completed, err_cnt=0, name="w"):
    return WorkerHealthInput(
        worker_id=wid, name=name, capability="cap",
        total=total, completed=completed, failed=total - completed,
        top_repeated_error_cnt=err_cnt, top_error_msg="boom" if err_cnt else None,
    )


# ── 体检 ──
def test_healthy_worker_not_flagged():
    assert scan_worker_health([_w("a", 100, 95)]) == []


def test_low_success_flagged():
    out = scan_worker_health([_w("a", 100, 50)])
    assert len(out) == 1 and out[0].worker_id == "a"


def test_insufficient_samples_not_flagged():
    # 9 < min_samples=10 → 不判（防噪声）
    assert scan_worker_health([_w("a", 9, 1)]) == []


def test_repeated_error_flagged_even_if_success_ok():
    # 成功率尚可，但同一错误高频重复 → 仍判候选
    out = scan_worker_health([_w("a", 100, 90, err_cnt=8)])
    assert len(out) == 1


def test_sorted_worst_first():
    out = scan_worker_health([_w("a", 100, 60), _w("b", 100, 30), _w("c", 100, 50)])
    assert [c.worker_id for c in out] == ["b", "c", "a"]


def test_threshold_override():
    th = WorkerHealthThresholds(success_rate_floor=0.5, min_samples=10, repeated_error_floor=5)
    assert scan_worker_health([_w("a", 100, 60)], th) == []  # 0.6 ≥ 0.5 floor


# ── 跨调用方兼容门 ──
def _c(sid, action, total, completed):
    return CallerStat(super_agent_id=sid, action=action, total=total, completed=completed)


def test_compat_no_regression():
    before = [_c("super1111", "publish", 50, 45), _c("super2222", "draft", 50, 48)]
    after = [_c("super1111", "publish", 50, 46), _c("super2222", "draft", 50, 47)]
    v = check_cross_caller_compat(before, after)
    assert v.compatible and v.regressed_callers == []


def test_compat_one_caller_regressed_blocks():
    before = [_c("super1111", "publish", 50, 45), _c("super2222", "draft", 50, 48)]
    after = [_c("super1111", "publish", 50, 46), _c("super2222", "draft", 50, 20)]  # super2 崩
    v = check_cross_caller_compat(before, after)
    assert not v.compatible
    assert len(v.regressed_callers) == 1 and "draft" in v.regressed_callers[0]


def test_compat_low_samples_skipped():
    # 样本不足的调用方不判退化（不拦改进）
    before = [_c("super1111", "publish", 3, 3)]
    after = [_c("super1111", "publish", 3, 0)]
    assert check_cross_caller_compat(before, after).compatible


def test_compat_new_caller_no_baseline():
    before = []
    after = [_c("superNEW0", "publish", 50, 40)]
    assert check_cross_caller_compat(before, after).compatible


def test_compat_within_tolerance_ok():
    # 小幅下滑在容差内（0.1）→ 不判退化
    before = [_c("super1111", "publish", 100, 90)]
    after = [_c("super1111", "publish", 100, 82)]  # 0.90→0.82，差 0.08 < 0.1
    assert check_cross_caller_compat(before, after).compatible
