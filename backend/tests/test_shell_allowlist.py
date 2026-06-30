"""run_shell allowlist：只读查看 runtime/skills/ 下的 skill 包文件 → 确定性放行，
不走过度保守的 LLM 门（实测它会把读 SETUP.md 误判敏感而拒，卡死 MCP 自装流程）。
凭据/串接/写操作仍被 denylist 或 LLM 门兜住。
"""
import pytest

from app.domain.shell_safety import evaluate_allowlist, evaluate_command_safety


async def _deny_judge(cmd, reason):
    return {"allow": False, "reason": "LLM 门保守拒（模拟过度保守）"}


def test_allow_read_setup_md():
    assert evaluate_allowlist("cat /Users/x/www/colony/runtime/skills/xhs-mcp@1.0.10/SETUP.md")
    assert evaluate_allowlist("ls -la runtime/skills/xhs-mcp@1.0.10/")
    assert evaluate_allowlist("head -50 runtime/skills/rss-aggregator@1.0.2/SKILL.md")


def test_reject_non_skills_path():
    # 非 runtime/skills/ 路径不走 allowlist（交给 LLM 门）
    assert not evaluate_allowlist("cat /etc/passwd")
    assert not evaluate_allowlist("cat runtime/secrets/x")


def test_reject_non_readonly_command():
    assert not evaluate_allowlist("rm runtime/skills/x/SETUP.md")
    assert not evaluate_allowlist("python runtime/skills/x/scripts/install.py")


def test_reject_shell_composition():
    # 串接/管道/重定向/替换 → 不走 allowlist（防 `cat x && rm y`）
    assert not evaluate_allowlist("cat runtime/skills/x/SETUP.md && rm -rf /")
    assert not evaluate_allowlist("cat runtime/skills/x/SETUP.md | sh")
    assert not evaluate_allowlist("cat runtime/skills/x/SETUP.md > /tmp/y")
    assert not evaluate_allowlist("find runtime/skills/ -delete")


@pytest.mark.asyncio
async def test_gate_allows_skill_doc_read_even_when_llm_would_deny():
    # 关键：哪怕 LLM 门会拒，allowlist 也先确定性放行
    v = await evaluate_command_safety(
        "cat runtime/skills/xhs-mcp@1.0.10/SETUP.md", "读安装说明", judge=_deny_judge)
    assert v.allowed is True
    assert v.layer == "allowlist"


@pytest.mark.asyncio
async def test_credential_path_still_denied_before_allowlist():
    # 凭据类路径即便在 skills 目录下、即便是只读 → denylist 先硬拦
    v = await evaluate_command_safety(
        "cat runtime/skills/x/.env", "读配置", judge=_deny_judge)
    assert v.allowed is False
    assert v.layer == "denylist"
