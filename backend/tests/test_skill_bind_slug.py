"""skill_bind 接受 slug：LLM 常直接传 'invoke_worker'，旧实现 uuid.UUID(slug) 直接报
'badly formed hexadecimal UUID'，逼它多绕一圈查 UUID，浪费一轮 turn 预算 → BUILD 做不完。
_resolve_skill_id 就地把 slug 解析成 UUID。
"""
from __future__ import annotations

import uuid

import pytest

from app.models.skill import Skill
from app.skills_builtin.builder.builder_skills import _resolve_skill_id

pytestmark = pytest.mark.asyncio


async def _seed_skill(db, slug: str) -> uuid.UUID:
    sid = uuid.uuid4()
    db.add(Skill(id=sid, slug=slug, name=slug, description="x", skill_type="tool_builtin"))
    await db.commit()
    return sid


async def test_resolves_slug_to_uuid(db_session):
    sid = await _seed_skill(db_session, "invoke_worker")
    assert await _resolve_skill_id(db_session, "invoke_worker") == sid


async def test_uuid_passes_through(db_session):
    sid = await _seed_skill(db_session, "list_workers")
    assert await _resolve_skill_id(db_session, str(sid)) == sid


async def test_unknown_slug_raises_helpful(db_session):
    with pytest.raises(ValueError, match="skill_list_available"):
        await _resolve_skill_id(db_session, "no_such_skill")
