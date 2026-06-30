"""MCP server startup_command

Revision ID: 032_mcp_startup_command
Revises: 031_wechat_outbox
Create Date: 2026-05-21

http 模式 MCP server 可能由 colony 外部进程启动（如 xiaohongshu-mcp 这个本地 go 二进制）。
当 worker 调 MCP 工具发现 server 挂了，可以调 `mcp_server_restart` skill 自动拉起来。
本字段存「拉起的 shell 命令向量」（如 ["/usr/local/bin/xhs-mcp", "--port", "18060"]）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "032_mcp_startup_command"
down_revision: str | None = "031_wechat_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("startup_command", sa.JSON(), nullable=True),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("startup_cwd", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "startup_cwd")
    op.drop_column("mcp_servers", "startup_command")
