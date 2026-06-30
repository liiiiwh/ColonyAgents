"""return_result · needs_clarification + result 同时给出时的软兜底（v7.6）

回归：qwen 等模型偶发同时传 needs_clarification=True 与 text，旧版 raise ValueError
让整个 worker invocation 崩溃 → super 误判 worker 故障并升级。现改为软兜底：不 raise，
保留 needs_clarification 语义，把 text 折进 clarification_questions。
"""
import asyncio
import json

import pytest

from app.skills_builtin.context import BuiltinToolContext
from app.skills_builtin.worker_io.worker_io_skills import return_result_tool


def _call(**kw):
    tool = return_result_tool(BuiltinToolContext(extra={"agent_id": "w-1"}))
    return json.loads(asyncio.get_event_loop().run_until_complete(tool.coroutine(**kw)))


def test_clarification_plus_text_does_not_raise():
    # 旧版会 raise ValueError；现在应正常返回
    env = _call(needs_clarification=True, text="我巡逻了3条评论但不确定账号")
    assert env["ok"] is True
    assert env["status"] == "needs_clarification"


def test_text_folded_into_clarification_questions():
    env = _call(needs_clarification=True, text="部分产出X")
    qs = env.get("clarification_questions") or []
    assert any("部分产出X" in q for q in qs), qs
    # 半成品结果字段不应作为成功结果泄露
    assert "text" not in env


def test_pure_clarification_unaffected():
    env = _call(needs_clarification=True, clarification_questions=["哪个账号？"])
    assert env["status"] == "needs_clarification"
    assert env["clarification_questions"] == ["哪个账号？"]


def test_pure_result_unaffected():
    env = _call(text="正常结果")
    assert env["status"] == "completed"
    assert env["text"] == "正常结果"
