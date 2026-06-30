"""ADR-028 D2 · Builder 协议硬规则：mcp_server_register 必须带 startup_command。

为什么硬：登录态 MCP（xhs/知乎）的 QR 登录走 readiness human-qr 卡，readiness
拉起 server（_spawn_and_wait）+ 探活（_fetch_qr_url）都依赖 startup_command。没它
就无法 Popen 拉起、拿不到二维码、QR 探活落空 → 登录闭环断。

run_shell 装完 → mcp_server_register(startup_command=...) → ensure_ready 的链路
必须写进 Builder「设计 super」协议（init_db Builder protocol_md 文案）。

纯文本断言协议源码字面量，不实跑 LLM/DB。
"""
from __future__ import annotations

import inspect

from app.db import init_db


def _builder_protocol_text() -> str:
    """从 seed_builder_project 源码里取协议字面量（含 Builder Supervisor protocol_md）。"""
    return inspect.getsource(init_db.seed_builder_project)


def test_builder_protocol_requires_startup_command_on_register():
    """mcp_server_register 必须带 startup_command 的硬规则文案存在。"""
    text = _builder_protocol_text()
    assert "startup_command" in text, "Builder 协议须提及 startup_command"
    # 硬规则强调：必须/required/否则无法拉起
    assert "mcp_server_register" in text


def test_builder_protocol_links_register_to_qr_probe():
    """硬规则须说明缺 startup_command 则无法 Popen 拉起 + QR 探活。"""
    text = _builder_protocol_text()
    # 关键词：无法 auto-launch / Popen / QR 探活
    assert ("auto-launch" in text or "Popen" in text or "拉起" in text), (
        "硬规则须解释 startup_command 用于拉起 MCP server"
    )
    assert ("QR" in text or "二维码" in text or "qr" in text), (
        "硬规则须把 startup_command 关联到 QR 探活/登录"
    )


def test_builder_protocol_install_then_register_then_ensure_ready_chain():
    """run_shell 装完 → register(startup_command) → ensure_ready 的链路文案。"""
    text = _builder_protocol_text()
    assert "run_shell" in text
    assert "mcp_ensure_ready" in text or "ensure_ready" in text
