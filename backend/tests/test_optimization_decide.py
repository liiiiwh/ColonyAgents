"""cand① 自优化闭环 · 决策状态机（纯函数，接口即测试面）。

把「等 LLM 记得调 L2」改成代码驱动闭环的核心判定：
信号快照 → 动作{none/propose/wait/keep/revert}。自动应用 + 自动评估 + 自动回滚。
"""
from app.domain.optimization.decide import OptAction, OptState, decide_optimization_action


def _s(**kw):
    base = dict(has_pending_change=False, samples_since_apply=0, eval_threshold=5,
                current_pass_rate=1.0, baseline_pass_rate=1.0, tolerance=0.1,
                regression=False, quota_remaining=3)
    base.update(kw)
    return OptState(**base)


def test_regression_with_quota_proposes():
    act, _ = decide_optimization_action(_s(regression=True, quota_remaining=2))
    assert act is OptAction.PROPOSE


def test_no_regression_does_nothing():
    act, _ = decide_optimization_action(_s(regression=False))
    assert act is OptAction.NONE


def test_regression_but_quota_exhausted_waits():
    act, _ = decide_optimization_action(_s(regression=True, quota_remaining=0))
    assert act is OptAction.NONE


def test_pending_change_not_enough_samples_waits():
    act, _ = decide_optimization_action(_s(has_pending_change=True, samples_since_apply=2, eval_threshold=5))
    assert act is OptAction.WAIT


def test_pending_change_held_up_keeps():
    act, _ = decide_optimization_action(_s(
        has_pending_change=True, samples_since_apply=6, eval_threshold=5,
        current_pass_rate=0.95, baseline_pass_rate=1.0, tolerance=0.1))
    assert act is OptAction.KEEP


def test_pending_change_regressed_reverts():
    act, _ = decide_optimization_action(_s(
        has_pending_change=True, samples_since_apply=6, eval_threshold=5,
        current_pass_rate=0.6, baseline_pass_rate=1.0, tolerance=0.1))
    assert act is OptAction.REVERT


def test_pending_evaluation_takes_priority_over_new_regression():
    # 有待评估的改动时，先评估，不叠新提案
    act, _ = decide_optimization_action(_s(
        has_pending_change=True, samples_since_apply=1, eval_threshold=5, regression=True))
    assert act is OptAction.WAIT
