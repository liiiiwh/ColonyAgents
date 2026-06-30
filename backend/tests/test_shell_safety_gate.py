"""ADR-010 R3 · run_shell 安全门编排：denylist → LLM 门 → default-deny。

judge 可注入（测试 mock 掉真实 LLM）。
"""
import pytest

from app.domain.shell_safety import evaluate_command_safety


@pytest.mark.asyncio
async def test_denylist_short_circuits_before_llm():
    called = []

    async def judge(cmd, reason):
        called.append(cmd)
        return {"allow": True}

    v = await evaluate_command_safety("rm -rf /", "cleanup", judge=judge)
    assert v.allowed is False
    assert v.layer == "denylist"
    assert called == []  # 灾难命令不浪费 LLM，直接硬拦


@pytest.mark.asyncio
async def test_gray_zone_judge_deny_honored():
    async def judge(cmd, reason):
        return {"allow": False, "reason": "看着像装了个不明二进制"}

    v = await evaluate_command_safety("./unknown-binary --daemon", "start", judge=judge)
    assert v.allowed is False
    assert v.layer == "llm_gate"
    assert "不明二进制" in (v.reason or "")


@pytest.mark.asyncio
async def test_judge_error_defaults_deny():
    async def judge(cmd, reason):
        raise RuntimeError("LLM 超时")

    v = await evaluate_command_safety("./xhs-mcp", "start", judge=judge)
    assert v.allowed is False
    assert v.layer == "llm_gate"


@pytest.mark.asyncio
async def test_judge_malformed_defaults_deny():
    async def judge(cmd, reason):
        return None  # 含糊/坏返回

    v = await evaluate_command_safety("./xhs-mcp", "start", judge=judge)
    assert v.allowed is False


@pytest.mark.asyncio
async def test_gray_zone_judge_allow_honored():
    async def judge(cmd, reason):
        return {"allow": True, "reason": "本地启动命令，安全"}

    v = await evaluate_command_safety("./xhs-mcp -port :18060", "start", judge=judge)
    assert v.allowed is True
    assert v.layer == "llm_gate"
