"""V7.3 · 行为步道标签 · daemon_prompts §3 区分用户实时插话 vs cron 自主运行。

ADR-007：用户消息标 [👤 用户实时插话·优先响应·人在现场]，cron 触发标 [⏰ 定时自主运行]，
让 super 见用户标签先回应再推进既定计划。
"""
from __future__ import annotations

import pytest


class _RS:
    def __init__(self, run_count=1, last_error=None):
        self.run_count = run_count
        self.last_error = last_error


def test_user_message_carries_priority_tag():
    from app.domain.daemon_prompts import assemble_super_prompt
    md = assemble_super_prompt(
        base_message="x",
        pending_user_msgs=[{"content": "提前看下数据分析", "created_at": None, "meta": {"source": "user_chat"}}],
        payload={"trigger": "user_chat"},
        runtime_state=_RS(),
    )
    assert "👤" in md or "用户实时插话" in md
    assert "优先响应" in md


def test_cron_trigger_marked_autonomous():
    from app.domain.daemon_prompts import assemble_super_prompt
    md = assemble_super_prompt(
        base_message="daily analysis",
        pending_user_msgs=[],
        payload={"trigger": "0 19 * * *"},
        runtime_state=_RS(),
    )
    assert "⏰" in md or "定时自主运行" in md


def test_user_chat_trigger_marked_interactive():
    from app.domain.daemon_prompts import assemble_super_prompt
    md = assemble_super_prompt(
        base_message="x",
        pending_user_msgs=[{"content": "hi", "created_at": None, "meta": {}}],
        payload={"trigger": "user_chat"},
        runtime_state=_RS(),
    )
    # §4 触发元数据应能看出是用户驱动
    assert "user_chat" in md
