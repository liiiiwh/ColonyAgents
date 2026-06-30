"""ADR-010 R1 · readiness manifest 模型 + 自动生成。

每个 MCP 一份 manifest：requirements[]，每项 (id, kind, probe, remediation)。
kind ∈ {auto-shell, human-qr, human-secret, human-tos, instructions}。
deployment ∈ {local, cloud} 选模板。生成据：部署类型 + 工具内省 + 需要的密钥。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# 工具名暗示「需要登录」→ human-qr
_LOGIN_PROBE_TOOLS = {"check_login_status", "get_login_qrcode"}


@dataclass
class Requirement:
    id: str
    kind: str
    probe: dict = field(default_factory=dict)
    remediation: dict = field(default_factory=dict)


@dataclass
class ReadinessManifest:
    deployment: str
    requirements: list[Requirement] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"deployment": self.deployment,
                "requirements": [asdict(r) for r in self.requirements]}

    @classmethod
    def from_dict(cls, d: dict) -> "ReadinessManifest":
        return cls(
            deployment=(d or {}).get("deployment", "local"),
            requirements=[Requirement(**r) for r in (d or {}).get("requirements", [])],
        )


def generate_manifest(
    *,
    deployment: str,
    tool_names: list[str] | None = None,
    startup_command: list[str] | None = None,
    secret_keys: list[str] | None = None,
) -> ReadinessManifest:
    tools = set(tool_names or [])
    reqs: list[Requirement] = []

    # 本地部署 + 有启动命令 → server 必须在跑（auto-shell 拉起）
    if deployment == "local" and startup_command:
        reqs.append(Requirement(
            id="server_up", kind="auto-shell",
            probe={"type": "http_health"},
            remediation={"type": "auto-shell", "source": "startup_command"},
        ))

    # 工具集暗示需要登录 → human-qr
    if tools & _LOGIN_PROBE_TOOLS:
        reqs.append(Requirement(
            id="logged_in", kind="human-qr",
            probe={"type": "mcp_tool", "tool": "check_login_status"},
            remediation={"type": "human-qr", "tool": "get_login_qrcode"},
        ))

    # 需要的密钥 → human-secret（每个 key 一项）
    for key in (secret_keys or []):
        reqs.append(Requirement(
            id=f"secret:{key}", kind="human-secret",
            probe={"type": "env_present", "key": key},
            remediation={"type": "human-secret", "key": key},
        ))

    return ReadinessManifest(deployment=deployment, requirements=reqs)
