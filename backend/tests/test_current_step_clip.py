"""mission_daemon._clip_step · current_step 列(255)兜底裁剪

回归：paused_reason 等长文案写入 String(64) current_step 时溢出
（StringDataRightTruncationError）。迁移 054 放宽到 255，_clip_step 再兜底。
"""
from app.services.mission_daemon import _STEP_MAX, _clip_step


def test_clip_none_passthrough():
    assert _clip_step(None) is None


def test_clip_short_untouched():
    s = "skip: paused (waiting capability)"
    assert _clip_step(s) == s


def test_clip_long_truncated_with_ellipsis():
    long = "skip: paused (" + "工" * 400 + ")"
    out = _clip_step(long)
    assert len(out) == _STEP_MAX
    assert out.endswith("…")


def test_clip_exact_boundary_untouched():
    s = "a" * _STEP_MAX
    assert _clip_step(s) == s


def test_clip_one_over_boundary():
    s = "a" * (_STEP_MAX + 1)
    out = _clip_step(s)
    assert len(out) == _STEP_MAX
