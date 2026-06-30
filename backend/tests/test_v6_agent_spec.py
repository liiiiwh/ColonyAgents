"""v6 · AgentSpec + Factory tracer tests.

行为：一份 SuperSpec / WorkerSpec dataclass → 一次事务化落库。
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def spec_db():
    """sqlite + 仅必需的 model 子集。"""
    from app.db.base import Base
    # 触发 model 注册（顺序很重要：先 user 再 provider 再 agent 再 skill 再 project）
    import app.models.user  # noqa
    import app.models.provider  # noqa
    import app.models.agent  # noqa
    import app.models.skill  # noqa
    import app.models.mission  # noqa
    import app.models.knowledge  # noqa

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # 只建必需表（不含 JSONB 的模型）
        for tname in (
            "users", "llm_providers", "llm_models",
            "agents", "skills", "agent_skills",
            "missions", "mission_run_state",
        ):
            tbl = Base.metadata.tables.get(tname)
            if tbl is not None:
                try:
                    await conn.run_sync(tbl.create)
                except Exception:
                    pass
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def test_super_spec_is_pydantic_dataclass():
    """Tracer #1：SuperSpec 是 pydantic dataclass，必填字段就是 name / goal_spec / model_id。"""
    from app.domain.builder import SuperSpec
    from pydantic import ValidationError

    # 缺 name 该 raise
    with pytest.raises((ValidationError, TypeError)):
        SuperSpec()

    s = SuperSpec(
        name="xhs-test",
        slug="xhs-test",
        model_id=uuid.uuid4(),
        goal_spec={"description": "运营小红书"},
        capabilities=["xhs_ops"],
    )
    assert s.name == "xhs-test"
    assert s.slug == "xhs-test"
    assert s.capabilities == ["xhs_ops"]


def test_worker_spec_required_capability_contract():
    """Tracer #2：WorkerSpec 必须有 capability + capability_contract。"""
    from app.domain.builder import WorkerSpec
    from pydantic import ValidationError

    with pytest.raises((ValidationError, TypeError)):
        WorkerSpec(name="x", slug="x", model_id=uuid.uuid4())  # missing capability

    w = WorkerSpec(
        name="test-worker", slug="test_worker", model_id=uuid.uuid4(),
        capability="test_cap",
        capability_contract={
            "capability": "test_cap", "version": "1.0.0",
            "advertises": [{"action": "ping"}],
        },
    )
    assert w.capability == "test_cap"


def test_validate_spec_rejects_invalid_kind_for_caps():
    """Tracer #3：spec 必填校验 + 命名 slug 规范。"""
    from app.domain.builder import WorkerSpec
    from pydantic import ValidationError
    with pytest.raises((ValidationError, ValueError)):
        WorkerSpec(name="x", slug="BAD SLUG WITH SPACE", model_id=uuid.uuid4(),
                   capability="x", capability_contract={})


def test_super_spec_extra_config_includes_goal_spec():
    """Tracer #4：to_extra_config() 把 goal_spec / capabilities 折成 agent.extra_config 形态。"""
    from app.domain.builder import SuperSpec
    s = SuperSpec(
        name="x", slug="x", model_id=uuid.uuid4(),
        goal_spec={"description": "desc", "completion_criteria": ["a", "b"]},
        capabilities=["xhs_ops", "zhihu_ops"],
        extra_config={"foo": "bar"},
    )
    ec = s.to_extra_config()
    assert ec["goal_spec"]["description"] == "desc"
    assert ec["required_capabilities"] == ["xhs_ops", "zhihu_ops"]
    assert ec["foo"] == "bar"  # 老 extra_config 字段保留


def test_worker_spec_extra_config_includes_capability_contract():
    """Tracer #5：worker spec.to_extra_config() 把 capability_contract 折进去。"""
    from app.domain.builder import WorkerSpec
    contract = {"capability": "x", "version": "1.0.0", "advertises": [{"action": "go"}]}
    w = WorkerSpec(
        name="x", slug="x", model_id=uuid.uuid4(),
        capability="x", capability_contract=contract,
    )
    ec = w.to_extra_config()
    assert ec["capability_contract"] == contract


def test_super_default_strong_brain_settings():
    """Tracer #6：SuperSpec 默认 enable_thinking=True / max_iter=40（R24 强大脑）。"""
    from app.domain.builder import SuperSpec
    s = SuperSpec(name="x", slug="x", model_id=uuid.uuid4())
    assert s.enable_thinking is True
    assert s.max_iterations == 40
    assert s.temperature == 0.5


def test_worker_default_strong_hands_settings():
    """Tracer #7：WorkerSpec 默认 enable_thinking=False / max_iter=12（R24 强落地）。"""
    from app.domain.builder import WorkerSpec
    w = WorkerSpec(
        name="x", slug="x", model_id=uuid.uuid4(),
        capability="x", capability_contract={"capability": "x", "advertises": []},
    )
    assert w.enable_thinking is False
    assert w.max_iterations == 12
    assert w.temperature == 0.3
