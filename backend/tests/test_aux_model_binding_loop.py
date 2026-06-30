"""Image/aux-model 绑定闭环（集成）。

回归保护一个真 bug：Builder 能用 build_worker 建出图片 worker 的架子，但 WorkerSpec 没有
aux_models 字段、apply_worker_spec 也从不落 AgentAuxModel —— 于是运行时 invoke_aux_model(role='image')
找不到 binding，worker「建得出却出不了图」。

本测试证明：WorkerSpec 带 aux_models → apply_worker_spec 在同一事务里把绑定落库。
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def spec_db():
    from app.db.base import Base
    import app.models.user  # noqa
    import app.models.provider  # noqa
    import app.models.agent  # noqa
    import app.models.skill  # noqa
    import app.models.mission  # noqa
    import app.models.knowledge  # noqa

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for tname in (
            "users", "llm_providers", "llm_models",
            "agents", "skills", "agent_skills", "agent_aux_models",
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


async def _seed(db) -> uuid.UUID:
    """种下 return_result skill + 一个 provider + 一个启用的 image 模型；返回 image 模型 UUID。"""
    from app.models.skill import Skill
    from app.models.provider import LLMProvider, LLMModel

    db.add(Skill(slug="return_result", name="Return Result", builtin_ref="return_result",
                 skill_type="tool_builtin", category="worker", description=""))
    prov = LLMProvider(name="volc", provider_type="volcengine", api_key="enc")
    db.add(prov)
    await db.flush()
    img = LLMModel(provider_id=prov.id, model_id="doubao-seedream-4-0-250828",
                   display_name="seedream-4", model_type="image", is_enabled=True)
    db.add(img)
    await db.commit()
    return img.id


def _worker_spec(image_model_uuid: uuid.UUID):
    from app.domain.builder import WorkerSpec
    return WorkerSpec(
        name="poster-maker", slug="poster_maker", model_id=uuid.uuid4(),
        capability="make_poster",
        capability_contract={
            "capability": "make_poster", "version": "1.0.0",
            "advertises": [{"action": "render", "side_effects": [], "requires_approval": False}],
        },
        aux_models=[{"role": "image", "model_id": str(image_model_uuid), "alias": "banana"}],
    )


@pytest.mark.asyncio
async def test_apply_worker_spec_persists_aux_image_binding(spec_db):
    from app.domain.builder.factory import apply_worker_spec
    from app.models.agent import AgentAuxModel

    async with spec_db() as db:
        image_uuid = await _seed(db)

    async with spec_db() as db:
        ref = await apply_worker_spec(db, _worker_spec(image_uuid), created_by=None)

    async with spec_db() as db:
        rows = (await db.execute(
            select(AgentAuxModel).where(AgentAuxModel.agent_id == ref.agent_id)
        )).scalars().all()
        assert len(rows) == 1, "image worker 必须落一条 image aux 绑定"
        assert rows[0].model_id == image_uuid
        assert rows[0].role == "image"
        assert rows[0].alias == "banana"


@pytest.mark.asyncio
async def test_persist_contract_aux_models_materializes_to_table(spec_db):
    """回归 e2e 抓到的真 bug：Builder 的 build-then-`agent_update(capability_contract={..,aux_models})`
    流把绑定只写进 extra_config.capability_contract，agent_aux_models 表里空 → 运行时
    _resolve_binding 读表找不到 → 「未找到辅助模型」出不了图。修复：materialize 到表。"""
    from app.domain.builder.factory import persist_contract_aux_models
    from app.models.agent import Agent, AgentAuxModel

    async with spec_db() as db:
        image_uuid = await _seed(db)
        w = Agent(name="probe", kind="worker", capability="img_gen_probe", model_id=None)
        db.add(w)
        await db.commit()
        wid = w.id

    async with spec_db() as db:
        n = await persist_contract_aux_models(
            db, wid,
            {"aux_models": [{"role": "image", "model_id": str(image_uuid), "alias": "banana"}]},
        )
        await db.commit()
        assert n == 1

    async with spec_db() as db:
        rows = (await db.execute(
            select(AgentAuxModel).where(AgentAuxModel.agent_id == wid)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].model_id == image_uuid
        assert rows[0].role == "image"
        assert rows[0].alias == "banana"


@pytest.mark.asyncio
async def test_persist_contract_aux_models_rejects_unknown(spec_db):
    """contract 里绑不存在的模型 → 抛 ValueError（调用方据此拒绝并回滚）。"""
    from app.domain.builder.factory import persist_contract_aux_models
    from app.models.agent import Agent

    async with spec_db() as db:
        await _seed(db)
        w = Agent(name="probe2", kind="worker", capability="img_gen_probe2", model_id=None)
        db.add(w)
        await db.commit()
        wid = w.id

    async with spec_db() as db:
        with pytest.raises(ValueError, match="aux model"):
            await persist_contract_aux_models(
                db, wid, {"aux_models": [{"role": "image", "model_id": str(uuid.uuid4())}]},
            )


@pytest.mark.asyncio
async def test_apply_worker_spec_rejects_unknown_aux_model(spec_db):
    """绑一个不存在的 aux 模型 → 抛错且回滚（不留半个 worker）。"""
    from app.domain.builder.factory import apply_worker_spec
    from app.models.agent import Agent

    async with spec_db() as db:
        await _seed(db)

    async with spec_db() as db:
        with pytest.raises(ValueError, match="aux model"):
            await apply_worker_spec(db, _worker_spec(uuid.uuid4()), created_by=None)

    async with spec_db() as db:
        rows = (await db.execute(select(Agent).where(Agent.kind == "worker"))).scalars().all()
        assert rows == [], "aux 绑定失败必须回滚，不留残缺 worker"
