"""ADR-010 R1 · readiness manifest 自动生成（据部署类型 + 工具内省 + 元数据推断）。

纯逻辑：给定 deployment / 工具名 / startup_command / 需要的密钥 → requirements。
"""
from app.domain.readiness import generate_manifest


def test_local_with_login_tool():
    m = generate_manifest(
        deployment="local",
        tool_names=["check_login_status", "get_login_qrcode", "publish_content"],
        startup_command=["/x/xhs-mcp", "-port", ":18060"],
        secret_keys=[],
    )
    assert m.deployment == "local"
    kinds = {r.id: r.kind for r in m.requirements}
    assert kinds["server_up"] == "auto-shell"
    assert kinds["logged_in"] == "human-qr"


def test_cloud_only_needs_key():
    m = generate_manifest(
        deployment="cloud",
        tool_names=["search", "fetch"],
        startup_command=None,
        secret_keys=["OPENAI_API_KEY"],
    )
    ids = [r.id for r in m.requirements]
    assert ids == ["secret:OPENAI_API_KEY"]  # 无 server_up、无登录
    assert m.requirements[0].kind == "human-secret"


def test_local_no_login_only_server():
    m = generate_manifest(
        deployment="local",
        tool_names=["do_thing"],
        startup_command=["/x/bin"],
        secret_keys=[],
    )
    assert [r.id for r in m.requirements] == ["server_up"]


def test_roundtrip_dict():
    m = generate_manifest(deployment="local", tool_names=["check_login_status"],
                          startup_command=["/x"], secret_keys=["K"])
    back = type(m).from_dict(m.to_dict())
    assert back.deployment == m.deployment
    assert [r.id for r in back.requirements] == [r.id for r in m.requirements]
