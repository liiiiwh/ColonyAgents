"""cand① · 双信号回归检测（纯函数）：quality_gate 通过率 + telemetry。"""
from app.domain.optimization.decide import RegressionMetrics, detect_regression


def _m(**kw):
    base = dict(pass_rate=1.0, pass_rate_floor=0.7, success_rate=1.0, success_rate_floor=0.7,
                top_repeated_error=0, repeated_error_floor=5, sample_count=20, min_samples=5)
    base.update(kw)
    return RegressionMetrics(**base)


def test_healthy_no_regression():
    reg, _ = detect_regression(_m())
    assert reg is False


def test_low_pass_rate_is_regression():
    reg, why = detect_regression(_m(pass_rate=0.5))
    assert reg is True and "通过率" in why


def test_low_success_rate_is_regression():
    reg, why = detect_regression(_m(success_rate=0.4))
    assert reg is True and "成功率" in why


def test_repeated_error_is_regression():
    reg, why = detect_regression(_m(top_repeated_error=8))
    assert reg is True and "重复" in why


def test_too_few_samples_suppresses():
    # 样本不足时不判回归，避免噪声触发自优化
    reg, _ = detect_regression(_m(pass_rate=0.1, sample_count=2, min_samples=5))
    assert reg is False


def test_none_metrics_no_data_no_regression():
    reg, _ = detect_regression(_m(pass_rate=None, success_rate=None, top_repeated_error=0))
    assert reg is False
