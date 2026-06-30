"""ADR-028 D2 · backend 镜像须装 MCP 运行时工具链（git + go + node）。

为跑第三方 MCP server（如 Go 写的 xiaohongshu-mcp）：run_shell 需能 git clone +
go build + node/npm 起服务。python:3.12-slim 基础镜像默认无这三者 → Dockerfile
必须显式 apt 装 git + go + node/npm。

纯文本断言 Dockerfile，不实跑 docker build（镜像重建由人工后续做）。
"""
from __future__ import annotations

from pathlib import Path


def _dockerfile_text() -> str:
    # backend/tests/ → backend/Dockerfile
    df = Path(__file__).resolve().parent.parent / "Dockerfile"
    return df.read_text(encoding="utf-8")


def test_dockerfile_installs_git():
    """run_shell 需要 git clone 第三方 MCP 仓库。"""
    text = _dockerfile_text()
    assert "git" in text, "Dockerfile 必须装 git（ADR-028 D2：clone 第三方 MCP）"


def test_dockerfile_installs_go():
    """xiaohongshu-mcp 等 Go 项目需 go 工具链构建。"""
    text = _dockerfile_text().lower()
    # 接受 `go`（golang apt 包名 golang / golang-go，或下载 go tar）
    assert "golang" in text or "go1." in text or "/usr/local/go" in text or "install go" in text, (
        "Dockerfile 必须装 go 工具链（ADR-028 D2：构建 Go 写的 MCP server）"
    )


def test_dockerfile_installs_node():
    """node/npm 起 node 系 MCP server。"""
    text = _dockerfile_text().lower()
    assert "node" in text or "npm" in text, (
        "Dockerfile 必须装 node/npm（ADR-028 D2：跑 node 系 MCP server）"
    )


def test_dockerfile_references_adr028_d2_rationale():
    """注释说明 ADR-028 D2 为跑第三方 MCP server。"""
    text = _dockerfile_text()
    assert "ADR-028" in text and "D2" in text, (
        "Dockerfile 工具链段落需注释引用 ADR-028 D2"
    )
