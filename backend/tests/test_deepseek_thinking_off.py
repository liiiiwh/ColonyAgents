"""DeepSeek 家族建出的 agent 强制 thinking_level='off'。

为什么必须在 create_agent 层强制：DeepSeek V4 thinking 只能靠 extra_body thinking:disabled 关，
其 reasoning_content 流式当前与链路不兼容（泄漏、变慢）。所以 deepseek agent 即使用户调高档位，
也必须落回 off，关参才会真正生效。

另：所有 kind 的思考档位默认 off（最省 token / 最快首 token）；需要更强思考由用户手动调高。
"""
from __future__ import annotations

import uuid

import pytest

from app.models.provider import LLMProvider, LLMModel
from app.schemas.agent import AgentCreate
from app.services import agent_service

pytestmark = pytest.mark.asyncio


async def _seed_model(db, provider_name, model_id, ptype="openai") -> str:
    pid = uuid.uuid4()
    db.add(LLMProvider(id=pid, name=provider_name, provider_type=ptype,
                       api_key="x", base_url="https://x"))
    mid = uuid.uuid4()
    db.add(LLMModel(id=mid, provider_id=pid, model_id=model_id,
                    display_name=model_id, model_type="chat"))
    await db.commit()
    return str(mid)


async def test_deepseek_super_forced_thinking_off(db_session):
    mid = await _seed_model(db_session, "deepseek", "deepseek-v4-pro")
    agent = await agent_service.create_agent(
        db_session,
        AgentCreate(name="ds-super", category="custom", kind="super",
                    model_id=mid, soul_md="x", protocol_md="x"),
    )
    assert agent.thinking_level == "off"
    assert agent.enable_thinking is False


async def test_non_deepseek_super_defaults_off(db_session):
    """对照：非 deepseek（如 qwen）super 也默认 off（不再强制开思考）。"""
    mid = await _seed_model(db_session, "aliyun", "qwen3.6-plus")
    agent = await agent_service.create_agent(
        db_session,
        AgentCreate(name="qw-super", category="custom", kind="super",
                    model_id=mid, soul_md="x", protocol_md="x"),
    )
    assert agent.thinking_level == "off"


async def test_deepseek_explicit_high_still_forced_off(db_session):
    """即使调用方显式传高档位，deepseek 也强制落回 off。"""
    mid = await _seed_model(db_session, "deepseek", "deepseek-v4-flash")
    agent = await agent_service.create_agent(
        db_session,
        AgentCreate(name="ds-worker", category="custom", kind="worker",
                    model_id=mid, soul_md="x", protocol_md="x",
                    thinking_level="high"),
    )
    assert agent.thinking_level == "off"
