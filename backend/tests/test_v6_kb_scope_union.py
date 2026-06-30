"""v6.C · knowledge_search 3-tier scope union 行为校验。

只检查 _format_hits + scope union 的逻辑不变量；不打真实 embedding/vector。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest


@pytest.mark.asyncio
async def test_knowledge_search_unions_mission_and_platform():
    """mission_kb 有命中 + platform_kb 有命中 → 输出按 score 排序且都出现。"""
    from app.skills_builtin.knowledge.knowledge_skills import knowledge_search_tool
    from app.skills_builtin.context import BuiltinToolContext

    mission_id = uuid.uuid4()

    mission_kb = MagicMock()
    mission_kb.id = uuid.uuid4()
    mission_kb.name = "kb-mission-x"
    mission_kb.mission_id = mission_id

    platform_kb = MagicMock()
    platform_kb.id = uuid.uuid4()
    platform_kb.name = "platform-shared"
    platform_kb.scope = "platform"

    mission_hits = [{"content": "mission tip A", "score": 0.6}]
    platform_hits = [{"content": "platform tip B", "score": 0.9}]

    async def fake_search(db, kb, query, top_k=5):
        if kb is mission_kb:
            return mission_hits
        if kb is platform_kb:
            return platform_hits
        return []

    fake_db = AsyncMock()
    class _CM:
        async def __aenter__(self_): return fake_db
        async def __aexit__(self_, *a): return False
    db_factory = lambda: _CM()

    ctx = BuiltinToolContext(
        mission_id=mission_id,
        db_factory=db_factory,
    )

    with patch("app.skills_builtin.knowledge.knowledge_skills.knowledge_service.get_kb_by_project", AsyncMock(return_value=mission_kb)), \
         patch("app.skills_builtin.knowledge.knowledge_skills.knowledge_service.get_platform_kb", AsyncMock(return_value=platform_kb)), \
         patch("app.skills_builtin.knowledge.knowledge_skills.knowledge_service.search", side_effect=fake_search):
        tool = knowledge_search_tool(ctx)
        out = await tool.coroutine(query="anything")

    assert "mission tip A" in out
    assert "platform tip B" in out
    # platform 应排在前面（score 更高）
    assert out.find("platform tip B") < out.find("mission tip A")
    # 标题应表明是 union
    assert "3-tier union" in out


@pytest.mark.asyncio
async def test_knowledge_search_no_union_when_kb_id_explicit():
    """显式 kb_id → 不 union platform（仅查指定 KB）。"""
    from app.skills_builtin.knowledge.knowledge_skills import knowledge_search_tool
    from app.skills_builtin.context import BuiltinToolContext

    target_kb = MagicMock()
    target_kb.id = uuid.uuid4()
    target_kb.name = "explicit-kb"

    async def fake_search(db, kb, query, top_k=5):
        return [{"content": "only this", "score": 0.7}]

    fake_db = AsyncMock()
    class _CM:
        async def __aenter__(self_): return fake_db
        async def __aexit__(self_, *a): return False
    db_factory = lambda: _CM()

    ctx = BuiltinToolContext(
        db_factory=db_factory,
    )

    get_kb_mock = AsyncMock(return_value=target_kb)
    get_platform_mock = AsyncMock()
    with patch("app.skills_builtin.knowledge.knowledge_skills.knowledge_service.get_kb", get_kb_mock), \
         patch("app.skills_builtin.knowledge.knowledge_skills.knowledge_service.get_platform_kb", get_platform_mock), \
         patch("app.skills_builtin.knowledge.knowledge_skills.knowledge_service.search", side_effect=fake_search):
        tool = knowledge_search_tool(ctx)
        out = await tool.coroutine(query="x", kb_id=str(target_kb.id))

    assert "only this" in out
    # platform 不应被访问
    get_platform_mock.assert_not_called()
    assert "3-tier union" not in out
