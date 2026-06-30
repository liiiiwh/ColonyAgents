"""cand① · 编排 cycle：决策 → 派发到对应 L2 动作（注入 fake 动作独测）。"""
import pytest

from app.domain.optimization.decide import OptState, OptAction, run_optimization_cycle


class _Spy:
    def __init__(self): self.calls = []
    async def propose(self, r): self.calls.append("propose")
    async def keep(self, r): self.calls.append("keep")
    async def revert(self, r): self.calls.append("revert")


def _s(**kw):
    base = dict(has_pending_change=False, samples_since_apply=0, eval_threshold=5,
                current_pass_rate=1.0, baseline_pass_rate=1.0, tolerance=0.1,
                regression=False, quota_remaining=3)
    base.update(kw)
    return OptState(**base)


@pytest.mark.asyncio
async def test_propose_dispatched_on_regression():
    spy = _Spy()
    act, _ = await run_optimization_cycle(_s(regression=True), spy)
    assert act is OptAction.PROPOSE and spy.calls == ["propose"]


@pytest.mark.asyncio
async def test_revert_dispatched_when_regressed():
    spy = _Spy()
    await run_optimization_cycle(_s(has_pending_change=True, samples_since_apply=6,
                                    current_pass_rate=0.5, baseline_pass_rate=1.0), spy)
    assert spy.calls == ["revert"]


@pytest.mark.asyncio
async def test_keep_dispatched_when_held():
    spy = _Spy()
    await run_optimization_cycle(_s(has_pending_change=True, samples_since_apply=6,
                                    current_pass_rate=0.95, baseline_pass_rate=1.0), spy)
    assert spy.calls == ["keep"]


@pytest.mark.asyncio
async def test_none_and_wait_dispatch_nothing():
    spy = _Spy()
    await run_optimization_cycle(_s(regression=False), spy)
    await run_optimization_cycle(_s(has_pending_change=True, samples_since_apply=1), spy)
    assert spy.calls == []
