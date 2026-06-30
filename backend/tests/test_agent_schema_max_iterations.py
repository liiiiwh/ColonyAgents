"""Builder Supervisor max_iterations=60（reclimit 120，给复杂构建留余量）必须能被
AgentPublic 序列化 + AgentUpdate 接受——否则 Agents 列表页 500、super 不可编辑。

回归：schema le=50 卡死 max_iterations=60 → /api/agents 序列化 ValidationError → 整页 500。
schema 上限对齐 SupervisorSpec（le=80）。
"""
import pytest

from app.schemas.agent import AgentPublic, AgentUpdate


def test_agent_public_accepts_max_iterations_60():
    import uuid
    from datetime import UTC, datetime

    a = AgentPublic.model_validate({
        "id": uuid.uuid4(),
        "name": "Builder Supervisor",
        "category": "builder",
        "kind": "super",
        "model_id": None,
        "max_iterations": 60,
        "is_enabled": True,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    })
    assert a.max_iterations == 60


def test_agent_update_accepts_max_iterations_60():
    u = AgentUpdate(max_iterations=60)
    assert u.max_iterations == 60


def test_max_iterations_still_capped_at_80():
    with pytest.raises(ValueError):
        AgentUpdate(max_iterations=81)
