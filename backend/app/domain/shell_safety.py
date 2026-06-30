"""ADR-010 R3 · run_shell 确定性 denylist 硬拦。

安全门第一层：灾难性命令模式直接拒，不交给概率 LLM 门。纯逻辑、可独测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DenylistVerdict:
    """denylist 判定。blocked=True 时 rule 给出命中的规则名（审计用）。"""

    blocked: bool
    rule: str | None = None


#: (规则名, 正则) —— 命中即硬拦。规则随 TDD 增量补充。
_DENY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("rm_rf", re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rf]")),
    ("privilege_escalation", re.compile(r"\b(sudo|doas|su)\b")),
    ("pipe_to_shell", re.compile(r"\b(curl|wget|fetch)\b.*\|\s*(sh|bash|zsh|fish|python\d?)\b")),
    ("credential_access", re.compile(
        r"(\.ssh/|\.aws/|\.env\b|id_rsa|id_ed25519|credentials\b|\.netrc|\.pgpass)"
    )),
]


def evaluate_denylist(command: str) -> DenylistVerdict:
    cmd = command or ""
    for name, pat in _DENY_RULES:
        if pat.search(cmd):
            return DenylistVerdict(blocked=True, rule=name)
    return DenylistVerdict(blocked=False)


# ── 确定性 allowlist：只读查看 skill 安装目录 → 直接放行，不走过度保守的 LLM 门 ──
# `runtime/skills/<slug>@<ver>/` 下是公开 ClawHub 包文件（SETUP.md / SKILL.md / scripts / _meta.json…），
# 不是凭据；LLM 门容易把"读 runtime 目录"误判为敏感而拒（实测挡住读 SETUP.md → MCP 自装流程卡住）。
# 凭据类路径（.env / id_rsa / .ssh / credentials …）仍被上面的 credential_access denylist 先硬拦。
_READONLY_VIEWERS = re.compile(
    r"^\s*(cat|head|tail|less|more|ls|stat|file|wc|grep|md5|md5sum|shasum|sha256sum)\b"
)
_SKILLS_PATH = re.compile(r"runtime/skills/")
# 任何 shell 串接 / 管道 / 重定向 / 替换 → 不走 allowlist（交给 LLM 门），避免 `cat x && rm y`
_SHELL_COMPOSITION = re.compile(r"[;&|><`$]|\bxargs\b|\bfind\b")


def evaluate_allowlist(command: str) -> bool:
    """只读查看 runtime/skills/ 下的文件/目录 → 确定性放行。"""
    cmd = command or ""
    if _SHELL_COMPOSITION.search(cmd):
        return False
    if not _READONLY_VIEWERS.match(cmd):
        return False
    return bool(_SKILLS_PATH.search(cmd))


@dataclass(frozen=True)
class SafetyVerdict:
    """安全门最终判定。layer ∈ {denylist, llm_gate}；allowed=True 才放行执行。"""

    allowed: bool
    layer: str
    rule: str | None = None
    reason: str | None = None


async def evaluate_command_safety(command: str, reason: str | None, *, judge) -> SafetyVerdict:
    """denylist 硬拦 → LLM 门（judge 可注入）→ default-deny。

    judge(command, reason) 应返回 {"allow": bool, "reason": str}；异常/含糊一律默认拒。
    """
    dv = evaluate_denylist(command)
    if dv.blocked:
        return SafetyVerdict(allowed=False, layer="denylist", rule=dv.rule,
                             reason=f"denylist 命中 {dv.rule}")
    # denylist 之后、LLM 门之前：确定性 allowlist 放行只读查看 skill 安装目录
    if evaluate_allowlist(command):
        return SafetyVerdict(allowed=True, layer="allowlist",
                             reason="只读查看 runtime/skills/ 下的 skill 包文件，确定性放行")
    try:
        verdict = await judge(command, reason)
    except Exception as exc:  # noqa: BLE001 — 门异常一律 default-deny
        return SafetyVerdict(allowed=False, layer="llm_gate",
                             reason=f"安全门异常，default-deny：{exc}")
    if not isinstance(verdict, dict) or not verdict.get("allow"):
        return SafetyVerdict(allowed=False, layer="llm_gate",
                             reason=(verdict or {}).get("reason") if isinstance(verdict, dict) else "门未明确放行")
    return SafetyVerdict(allowed=True, layer="llm_gate", reason=verdict.get("reason"))
