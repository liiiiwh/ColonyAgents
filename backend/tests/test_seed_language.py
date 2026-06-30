"""ADR-019(修订)/ADR-020 · 两个用户对话 super 的双语 soul + reseed_system_agents_language。

决策：只双语 soul（身份+对话语言来源），protocol 单份英文。reseed 按 SeedLanguage 在
Builder Supervisor + Colony Worker Optimization 的 soul 间切换（幂等）。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.init_db import reseed_system_agents_language
from app.db.system_agent_prompts import (
    BUILDER_SUPERVISOR_NAME,
    SYSTEM_SUPER_SOULS,
    WORKER_OPT_NAME,
    soul_for,
)
from app.models.agent import Agent

pytestmark = pytest.mark.asyncio


# ── 纯：双语 soul ──

def test_soul_for_bilingual():
    assert "English" in soul_for(BUILDER_SUPERVISOR_NAME, "en")
    assert "简体中文" in soul_for(BUILDER_SUPERVISOR_NAME, "zh")
    assert "English" in soul_for(WORKER_OPT_NAME, "en")
    assert "简体中文" in soul_for(WORKER_OPT_NAME, "zh")
    # 未知 lang → 回退 en；未知 name → None
    assert soul_for(BUILDER_SUPERVISOR_NAME, "fr") == soul_for(BUILDER_SUPERVISOR_NAME, "en")
    assert soul_for("不存在的 super", "en") is None


def test_only_two_user_facing_supers():
    assert set(SYSTEM_SUPER_SOULS) == {BUILDER_SUPERVISOR_NAME, WORKER_OPT_NAME}


# ── DB：reseed 切换 ──

async def _mk_super(db, name: str) -> uuid.UUID:
    ag = Agent(name=name, category="custom", kind="super", model_id=None,
               soul_md="OLD SOUL", protocol_md="x", is_system=True)
    db.add(ag)
    await db.flush()
    return ag.id


async def test_reseed_switches_souls_idempotent(db_session):
    bid = await _mk_super(db_session, BUILDER_SUPERVISOR_NAME)
    await _mk_super(db_session, WORKER_OPT_NAME)
    await db_session.commit()

    assert await reseed_system_agents_language(db_session, "zh") == 2
    b = (await db_session.execute(select(Agent).where(Agent.id == bid))).scalar_one()
    assert "简体中文" in b.soul_md

    # 幂等：已是目标态 → 0
    assert await reseed_system_agents_language(db_session, "zh") == 0

    # 切回 en
    assert await reseed_system_agents_language(db_session, "en") == 2
    b2 = (await db_session.execute(select(Agent).where(Agent.id == bid))).scalar_one()
    assert "English" in b2.soul_md
