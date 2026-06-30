"""V7.0 · Agent 每次调用注入当前时间（Y-m-d H:i:s + Asia/Shanghai + 周几）。

cron 自判去重的前提：super 必须知道「现在几点」才能对比 mission memory 判断今日是否已做。
注入点 = _collect_static_prompt_parts（所有 agent 共享的 system prompt 拼装）。
"""
from __future__ import annotations

import re

import pytest


def test_current_time_section_pure_helper():
    """纯函数：返回 ## 当前时间 段，含 Y-m-d H:i:s + 时区 + 周几。"""
    from app.domain.prompt_time import current_time_section
    s = current_time_section()
    assert "## 当前时间" in s
    # Y-m-d H:i:s 格式
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", s)
    # 时区标签（必需，否则 cron 7点歧义）
    assert "Asia/Shanghai" in s
    # 周几
    assert re.search(r"周[一二三四五六日]", s)


def test_current_time_section_accepts_injected_now():
    """可注入固定时间（测试确定性）。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.domain.prompt_time import current_time_section
    fixed = datetime(2026, 6, 2, 16, 39, 32, tzinfo=ZoneInfo("Asia/Shanghai"))
    s = current_time_section(now=fixed)
    assert "2026-06-02 16:39:32" in s
    assert "周二" in s  # 2026-06-02 是周二


def test_system_prompt_includes_current_time():
    """_collect_static_prompt_parts 注入时间段（所有 agent 都拿得到）。"""
    from app.services.agent_service import _collect_static_prompt_parts

    class _FakeSkillBinding:
        skill = None

    class _FakeAgent:
        soul_md = "我是测试 agent"
        protocol_md = ""
        skills = []
        domain_memory_md = ""

    parts = _collect_static_prompt_parts(_FakeAgent())
    joined = "\n".join(parts)
    assert "## 当前时间" in joined
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", joined)


def test_scheduler_uses_shanghai_timezone():
    """AsyncIOScheduler 钉死 Asia/Shanghai（消除「7点变凌晨3点」潜伏 bug）。"""
    import inspect
    from app.services import scheduler_service
    src = inspect.getsource(scheduler_service)
    assert 'AsyncIOScheduler(timezone="Asia/Shanghai")' in src or \
           "timezone=\"Asia/Shanghai\"" in src or "ZoneInfo(\"Asia/Shanghai\")" in src, \
        "scheduler 必须显式 Asia/Shanghai 时区"
