"""v6.B · list_supers + emit_redirect_suggestion tracer.

list_supers: super 看平台其它 super 候选（exclude self；按 keyword 模糊 +
capabilities 关键词）。emit_redirect_suggestion: 写 ActivityKind.REDIRECT
活动 + 卡片消息到 chat 流。
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def db_session():
    from app.db.base import Base
    import app.models.user  # noqa
    import app.models.provider  # noqa
    import app.models.agent  # noqa
    import app.models.skill  # noqa
    import app.models.mission  # noqa

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for tname in (
            "users", "llm_providers", "llm_models",
            "skills", "mcp_servers",
            "agents", "agent_skills", "agent_mcp_servers", "agent_aux_models",
            "missions", "mission_run_state", "mission_nodes",
        ):
            tbl = Base.metadata.tables.get(tname)
            if tbl is not None:
                try:
                    await conn.run_sync(tbl.create)
                except Exception:
                    pass
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def supers_seed(db_session):
    """种 3 个 super agent + 2 个 worker（worker 应该不被 list_supers 返回）。"""
    from app.models.agent import Agent

    rows = []
    for name, slug, cap_desc in [
        ("xhs_ops_super", "xhs-ops", "小红书运营 (发帖、巡评论、看数据)"),
        ("zhihu_ops_super", "zhihu-ops", "知乎运营 (写答案、巡查)"),
        ("video_writer_super", "video-writer", "短视频脚本生成"),
    ]:
        a = Agent(
            id=uuid.uuid4(), name=name, kind="super",
            category="custom", model_id=uuid.uuid4(),
            soul_md=cap_desc, protocol_md="",
            description=cap_desc, is_enabled=True,
        )
        db_session.add(a)
        rows.append(a)
    # 2 个 worker（不应该被 list_supers 返回）
    db_session.add(Agent(id=uuid.uuid4(), name="xhs_worker", kind="worker",
                         capability="xhs_ops", category="worker.custom",
                         model_id=uuid.uuid4(), soul_md="", protocol_md="", is_enabled=True))
    db_session.add(Agent(id=uuid.uuid4(), name="zhihu_worker", kind="worker",
                         capability="zhihu_ops", category="worker.custom",
                         model_id=uuid.uuid4(), soul_md="", protocol_md="", is_enabled=True))
    await db_session.commit()
    return {"db": db_session, "supers": rows}


@pytest.mark.asyncio
async def test_list_supers_returns_only_kind_super(supers_seed):
    """Tracer #1：list_supers 返回 kind='super' 且 is_enabled=True 的 agent。"""
    from app.domain.builder.list_supers import list_supers

    rows = await list_supers(supers_seed["db"])
    assert len(rows) == 3
    assert {r["name"] for r in rows} == {"xhs_ops_super", "zhihu_ops_super", "video_writer_super"}


@pytest.mark.asyncio
async def test_list_supers_excludes_self(supers_seed):
    """Tracer #2：传入 exclude_super_id 时不返回该 super 自己（不能给自己推荐自己）。"""
    from app.domain.builder.list_supers import list_supers

    me = supers_seed["supers"][0]
    rows = await list_supers(supers_seed["db"], exclude_super_id=me.id)
    names = {r["name"] for r in rows}
    assert "xhs_ops_super" not in names
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_list_supers_keyword_filter_matches_name_or_description(supers_seed):
    """Tracer #3：keyword='视频' 应只匹配 video_writer_super (descr 含 "短视频")。"""
    from app.domain.builder.list_supers import list_supers

    rows = await list_supers(supers_seed["db"], keyword="视频")
    assert len(rows) == 1
    assert rows[0]["name"] == "video_writer_super"


@pytest.mark.asyncio
async def test_list_supers_returns_fit_fields(supers_seed):
    """Tracer #4：返回 dict 含 super_id / slug / name / description / fit_hint 字段。
    fit_hint 是从 description 提的 1 句话；让 super LLM 排序时不必读 soul_md。"""
    from app.domain.builder.list_supers import list_supers

    rows = await list_supers(supers_seed["db"], keyword="运营")
    assert len(rows) >= 2
    r = rows[0]
    for k in ("super_id", "name", "description", "fit_hint"):
        assert k in r
