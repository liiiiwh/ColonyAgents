"""R2-1 第 2 段 · WorkerInvocation envelope parser 抽到 app/domain/dispatch/envelope.py。

worker LLM 调 return_result 返回的 ToolMessage 解析逻辑 — 纯函数 unit-testable。
"""
from __future__ import annotations

import json

import pytest


class _FakeToolMsg:
    """模拟 LangChain ToolMessage 的最小接口。"""
    def __init__(self, content: str, type_: str = "tool"):
        self.type = type_
        self.content = content


class _FakeAIMsg:
    def __init__(self, content: str):
        self.type = "ai"
        self.content = content


def test_extract_finds_completed_envelope_in_last_tool_message():
    from app.domain.dispatch.envelope import extract_return_result_envelope

    msgs = [
        _FakeAIMsg("planning..."),
        _FakeToolMsg(json.dumps({"status": "completed", "summary": "done", "data": {"id": 1}})),
    ]
    env = extract_return_result_envelope(msgs)
    assert env is not None
    assert env["status"] == "completed"
    assert env["data"]["id"] == 1


def test_extract_returns_needs_clarification():
    from app.domain.dispatch.envelope import extract_return_result_envelope

    msgs = [
        _FakeToolMsg(json.dumps({"status": "needs_clarification", "question": "which account?"})),
    ]
    env = extract_return_result_envelope(msgs)
    assert env is not None
    assert env["status"] == "needs_clarification"


def test_extract_returns_none_when_no_tool_msg():
    from app.domain.dispatch.envelope import extract_return_result_envelope

    msgs = [_FakeAIMsg("just a text reply, no tool call")]
    assert extract_return_result_envelope(msgs) is None


def test_extract_skips_unrelated_tool_message():
    """tool message 但不是 return_result（status 字段非 completed/needs_clarification）→ skip。"""
    from app.domain.dispatch.envelope import extract_return_result_envelope

    msgs = [
        _FakeToolMsg(json.dumps({"status": "fetched", "data": [1, 2]})),  # 别的 tool
        _FakeAIMsg("done"),
    ]
    assert extract_return_result_envelope(msgs) is None


def test_extract_skips_malformed_json():
    from app.domain.dispatch.envelope import extract_return_result_envelope

    msgs = [_FakeToolMsg("not json at all")]
    assert extract_return_result_envelope(msgs) is None


def test_extract_takes_latest_when_multiple():
    """两条都是 return_result，取最新（reversed iteration）。"""
    from app.domain.dispatch.envelope import extract_return_result_envelope

    msgs = [
        _FakeToolMsg(json.dumps({"status": "completed", "summary": "first"})),
        _FakeAIMsg("retry"),
        _FakeToolMsg(json.dumps({"status": "completed", "summary": "second"})),
    ]
    env = extract_return_result_envelope(msgs)
    assert env["summary"] == "second"
