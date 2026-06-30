"""全局 pytest fixtures。

使用 in-memory SQLite + aiosqlite 跑单元 / API 测试，避免依赖外部 Postgres。
涉及 pgvector / JSONB / LangGraph checkpoint 的集成测试走单独的 `tests/integration/` 目录，
通过 `@pytest.mark.pg` 标记并在无 DATABASE_URL_TEST 时自动跳过。
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

# 在 import 任何 app 模块之前设置 ENCRYPTION_KEY，
# 否则 core.encryption 的 Fernet 初始化会失败
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long-xyz")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("INIT_ADMIN_USERNAME", "admin")
os.environ.setdefault("INIT_ADMIN_PASSWORD", "admin123")
os.environ.setdefault("INIT_ADMIN_EMAIL", "admin@example.com")

# 测试加速：bcrypt 默认 12 rounds ≈ 200ms/次；测试里每次 login 都做 verify +
# seed_admin 做 hash。把 rounds 降到 4（~1ms）后全量回归从 230s → ~60s。
# 只影响测试进程；生产照常 12 rounds。
from passlib.context import CryptContext  # noqa: E402

import app.core.security as _security  # noqa: E402

_security.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.deps import get_db
from app.db.base import Base
from app.db.base_all import *  # noqa: F403 — 注册所有模型到 metadata
from app.db.init_db import seed_admin_user
from app.main import app as fastapi_app
from app.services import agent_service, provider_service


@pytest_asyncio.fixture
async def db_engine():
    """每个测试独立的 in-memory SQLite 引擎。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # system_settings 没有 ORM 模型（迁移 038 raw DDL 建表），create_all 不会建它。
        # 测试 DB 也建出来，让 system_settings.get / KB-on-create 等路径与生产一致（否则
        # 共享 session 上 "no such table" 报错会污染后续写入）。JSONB→TEXT、now()→CURRENT_TIMESTAMP。
        from sqlalchemy import text as _ddl

        await conn.execute(_ddl(
            "CREATE TABLE IF NOT EXISTS system_settings ("
            "key VARCHAR(128) PRIMARY KEY, value TEXT NOT NULL, description VARCHAR(512) NULL, "
            "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_by VARCHAR(128) NULL)"
        ))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_db(db_session: AsyncSession) -> AsyncSession:
    """预置管理员账号的 DB Session。"""
    await seed_admin_user(db_session)
    return db_session


@pytest_asyncio.fixture
async def _patched_session_local(db_engine, monkeypatch: pytest.MonkeyPatch):
    """让 `app.db.session.AsyncSessionLocal` 指向测试 engine。

    chat SSE endpoint 与 builtin tools 通过此 factory 在后台任务里开启新 Session。
    """
    test_local = async_sessionmaker(db_engine, expire_on_commit=False)
    from app.db import session as _db_session_mod

    monkeypatch.setattr(_db_session_mod, "AsyncSessionLocal", test_local)
    return test_local


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession, _patched_session_local
) -> AsyncGenerator[AsyncClient, None]:
    """httpx AsyncClient + 依赖覆盖，将 get_db 指向测试 session。"""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_client(
    seeded_db: AsyncSession, _patched_session_local
) -> AsyncGenerator[AsyncClient, None]:
    """已播种 admin 账号的 AsyncClient。"""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield seeded_db

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def admin_credentials() -> dict[str, str]:
    return {"username": "admin", "password": "admin123"}


# ──────────────── Provider fetchers mock ────────────────
# 避免测试触达真实 OpenAI / Gemini 等 HTTP API
_FAKE_CATALOG: dict[str, list[dict]] = {
    "openai": [
        {
            "model_id": "gpt-4o",
            "display_name": "GPT-4o",
            "model_type": "chat",
            "context_window": 128000,
            "supports_vision": True,
            "supports_function_calling": True,
        },
        {
            "model_id": "gpt-4o-mini",
            "display_name": "GPT-4o mini",
            "model_type": "chat",
            "context_window": 128000,
            "supports_function_calling": True,
        },
        {
            "model_id": "text-embedding-3-small",
            "display_name": "Embedding 3 Small",
            "model_type": "embedding",
            "context_window": 8191,
        },
        {
            "model_id": "text-embedding-3-large",
            "display_name": "Embedding 3 Large",
            "model_type": "embedding",
            "context_window": 8191,
        },
    ],
    "gemini": [
        {
            "model_id": "gemini-2.5-pro",
            "display_name": "Gemini 2.5 Pro",
            "model_type": "chat",
            "context_window": 1048576,
            "supports_vision": True,
            "supports_function_calling": True,
        },
        {
            "model_id": "text-embedding-004",
            "display_name": "Gemini Embedding 004",
            "model_type": "embedding",
        },
    ],
    "anthropic": [
        {
            "model_id": "claude-3-5-sonnet-latest",
            "display_name": "Claude 3.5 Sonnet",
            "model_type": "chat",
            "context_window": 200000,
        }
    ],
    "deepseek": [
        {"model_id": "deepseek-chat", "display_name": "DeepSeek Chat", "model_type": "chat"}
    ],
    "ollama": [{"model_id": "llama3.2", "display_name": "Llama 3.2", "model_type": "chat"}],
    "azure": [],
    "custom": [],
}


@pytest.fixture(autouse=True)
def mock_provider_fetchers(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有测试默认使用固定的假模型目录，不发出真实 HTTP 请求。"""
    fakes: dict[str, provider_service.ModelFetcher] = {}
    for ptype, catalog in _FAKE_CATALOG.items():
        items = list(catalog)

        async def _fake(*, api_key: str = "", base_url: str | None = None, _items=items, **__):
            return list(_items)

        fakes[ptype] = _fake
    monkeypatch.setattr(provider_service, "MODEL_FETCHERS", fakes)


class _FakeAsyncIterator:
    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration as e:
            raise StopAsyncIteration from e


class _FakeExecutor:
    """测试用：模拟 LangGraph create_react_agent，产出固定 text-delta 事件。"""

    def astream_events(self, input_, *, version="v2", **_):
        # V7.5 · 兼容 HumanMessage 对象 + dict 消息（daemon V7.2 传真 HumanMessage）
        _msgs = (input_ or {}).get("messages") or [{"content": ""}]
        _last = _msgs[-1]
        msg = getattr(_last, "content", None)
        if msg is None and isinstance(_last, dict):
            msg = _last.get("content", "")
        msg = msg or ""

        class _Chunk:
            content = f"[fake-llm] 收到：{msg}"

        events = [
            {
                "event": "on_chat_model_stream",
                "data": {"chunk": _Chunk()},
                "run_id": "fake-llm-run",
            }
        ]
        return _FakeAsyncIterator(events)

    async def ainvoke(self, input_, *args, **kwargs):
        """供 daemon run_once 等非 streaming 路径调用。"""
        import langchain_core.messages as _msgs

        msgs = (input_ or {}).get("messages") or []
        last_text = ""
        if msgs:
            content = getattr(msgs[-1], "content", None)
            if isinstance(content, str):
                last_text = content
            elif isinstance(msgs[-1], dict):
                last_text = msgs[-1].get("content", "")
        return {
            "messages": list(msgs) + [
                _msgs.AIMessage(content=f"[fake-llm] 收到：{last_text}")
            ]
        }


class _FakeChunk:
    """模拟 ChatGenerationChunk —— 只要有 .message.content 即可。"""

    class _Msg:
        def __init__(self, s: str) -> None:
            self.content = s

    def __init__(self, s: str) -> None:
        self.message = self._Msg(s)


class _FakeLLM:
    """测试用 LLM：_astream / ainvoke 都返回固定文字。"""

    streaming = True
    model_kwargs: dict = {}

    async def _astream(self, messages, *args, **kwargs):
        last = messages[-1].content if messages else ""
        yield _FakeChunk(f"[fake-llm] 收到：{last}")

    async def ainvoke(self, messages, *args, **kwargs):
        last = messages[-1].content if messages else ""
        return _FakeChunk(f"[fake-llm] 收到：{last}")


# 保留原始 _build_llm 引用，供 test_thinking_policy 这类需要观察 kwargs 的单测恢复
ORIGINAL_BUILD_LLM = agent_service._build_llm


@pytest.fixture(autouse=True)
def mock_agent_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试不触发真实 LiteLLM / LangGraph；返回固定文字流。"""

    async def _fake_build(db, agent, *, ctx, checkpointer=None, llm_override=None):
        return _FakeExecutor()

    async def _fake_build_llm(db, model, agent):
        return _FakeLLM()

    monkeypatch.setattr(agent_service, "build_agent_executor", _fake_build)
    monkeypatch.setattr(agent_service, "_build_llm", _fake_build_llm)


@pytest.fixture(autouse=True)
def mock_approval_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-028 D1（修订）· request_approval 服务端会真起 approval_judge LLM 判 must_human。
    测试里旁路掉（默认 must_human=False = routine），让现有 auto_approve 行为稳定；
    需要验「人工门停下」的测试自行 monkeypatch 本函数返回 (True, ...)。"""
    from app.services import approval_judge_service

    async def _fake_judge(db, mission, *, title, message, options, auto_approve_on, context=""):
        return False, "test-default routine"

    monkeypatch.setattr(approval_judge_service, "judge_must_human", _fake_judge)
