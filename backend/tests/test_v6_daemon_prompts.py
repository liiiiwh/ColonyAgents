"""R5-2 · DaemonPromptBuilder · daemon tick 的 5 段 prompt 拼装（纯）从 mission_daemon 搬出。

§3 pending 消息 / §4 trigger 元数据 / §5 runtime hint。无 DB，纯字符串。
"""
from __future__ import annotations

import pytest


class _RS:
    def __init__(self, run_count=1, last_error=None):
        self.run_count = run_count
        self.last_error = last_error


def test_assemble_includes_pending_user_messages():
    from app.domain.daemon_prompts import assemble_super_prompt
    md = assemble_super_prompt(
        base_message="cron tick",
        pending_user_msgs=[{"content": "改成晚上发", "created_at": None, "meta": {}}],
        payload={"trigger": "user_chat"},
        runtime_state=_RS(run_count=3),
    )
    assert "§3" in md
    assert "改成晚上发" in md


def test_assemble_empty_pending_marks_placeholder():
    from app.domain.daemon_prompts import assemble_super_prompt
    md = assemble_super_prompt(
        base_message="tick", pending_user_msgs=[], payload={}, runtime_state=_RS(),
    )
    assert "§3 empty" in md


def test_assemble_trigger_metadata_section():
    from app.domain.daemon_prompts import assemble_super_prompt
    md = assemble_super_prompt(
        base_message="hello", pending_user_msgs=[],
        payload={"trigger": "cron", "task": "publish", "task_group": "tg1"},
        runtime_state=_RS(run_count=7),
    )
    assert "§4" in md
    assert "cron" in md
    assert "tick #7" in md
    # §4 显式带 task，super 不用从 cron 猜本轮干啥
    assert "task: `publish`" in md


def test_assemble_runtime_hint_cancel_resumed():
    from app.domain.daemon_prompts import assemble_super_prompt
    md = assemble_super_prompt(
        base_message="x", pending_user_msgs=[], payload={}, runtime_state=_RS(),
        cancel_resumed=True,
    )
    assert "§5" in md
    assert "cancel" in md.lower()


def test_assemble_runtime_hint_last_error():
    from app.domain.daemon_prompts import assemble_super_prompt
    md = assemble_super_prompt(
        base_message="x", pending_user_msgs=[], payload={}, runtime_state=_RS(last_error="boom"),
    )
    assert "boom" in md
