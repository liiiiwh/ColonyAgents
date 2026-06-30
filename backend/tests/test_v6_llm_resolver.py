"""R4-1 · LlmResolver · 修分层倒置（service 不再 local-import api/preview_chat）。

把 _resolve_default_chat_llm 搬到 app/services/llm_resolver.py。
可测核心 = spec 解析：'provider/model' 消歧 / 裸 model_id 唯一性 / 缺失或重名报错。
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def db_session():
    from app.db.base import Base
    import app.models.provider  # noqa

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        for tname in ("llm_providers", "llm_models"):
            tbl = Base.metadata.tables.get(tname)
            if tbl is not None:
                await conn.run_sync(tbl.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_model(db, provider_name, model_id, ptype="custom"):
    from app.models.provider import LLMProvider, LLMModel
    pid = uuid.uuid4()
    db.add(LLMProvider(id=pid, name=provider_name, provider_type=ptype,
                       api_key="x", base_url="https://x"))
    mid = uuid.uuid4()
    db.add(LLMModel(id=mid, provider_id=pid, model_id=model_id,
                    display_name=model_id, model_type="chat"))
    await db.commit()
    return mid


@pytest.mark.asyncio
async def test_resolve_by_provider_slash_model(db_session):
    from app.services.llm_resolver import resolve_model_for_default_spec
    await _seed_model(db_session, "nebula", "claude-opus-4-6")
    await _seed_model(db_session, "aliyun", "claude-opus-4-6")  # 同 model_id 不同 provider
    m = await resolve_model_for_default_spec(db_session, "nebula/claude-opus-4-6")
    assert m.model_id == "claude-opus-4-6"


@pytest.mark.asyncio
async def test_resolve_bare_model_id_unique(db_session):
    from app.services.llm_resolver import resolve_model_for_default_spec
    await _seed_model(db_session, "nebula", "qwen3-plus")
    m = await resolve_model_for_default_spec(db_session, "qwen3-plus")
    assert m.model_id == "qwen3-plus"


@pytest.mark.asyncio
async def test_resolve_bare_ambiguous_raises(db_session):
    """裸 model_id 在多 provider 重名 → 报错要求消歧。"""
    from app.services.llm_resolver import resolve_model_for_default_spec
    await _seed_model(db_session, "nebula", "claude-opus-4-6")
    await _seed_model(db_session, "aliyun", "claude-opus-4-6")
    with pytest.raises(RuntimeError, match="重名|消歧"):
        await resolve_model_for_default_spec(db_session, "claude-opus-4-6")


@pytest.mark.asyncio
async def test_resolve_missing_raises(db_session):
    from app.services.llm_resolver import resolve_model_for_default_spec
    with pytest.raises(RuntimeError, match="未找到"):
        await resolve_model_for_default_spec(db_session, "no-such-model")


def test_services_no_longer_import_from_api():
    """分层倒置已修：service 层不再 local-import app.api（ADR-018：preview_chat 已删）。"""
    import inspect
    from app.services import compression_service, messaging_service, wechat_intent, mission_test_runner
    for mod in (compression_service, messaging_service, wechat_intent, mission_test_runner):
        src = inspect.getsource(mod)
        assert "from app.api." not in src and "import app.api" not in src, (
            f"{mod.__name__} 仍 local-import app.api（分层倒置未修）"
        )
