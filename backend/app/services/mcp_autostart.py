"""平台启动时自动拉起「本地 http MCP server」。

背景：http 型 MCP（如 xhs-mcp / weibo-mcp 这类用户本机起 binary 的）不像 stdio 型由
langchain-mcp-adapters 自带 spawn —— 冷启动后没人把它拉起来，worker 调用就会 connect
refused。本模块在 app 启动时，对所有 `is_enabled + server_type='http' + 配了
startup_command` 的 MCPServer 做：探活 → 没活就 spawn detached 子进程 → 轮询健康。

幂等：已经活着的直接跳过（reused）。best-effort：任何失败只记日志，绝不阻塞启动。
与 builder_skills.mcp_server_restart 同一套拉起逻辑（worker 运行期自愈用那条）。
"""
from __future__ import annotations

import asyncio
import logging
import subprocess

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import MCPServer

logger = logging.getLogger(__name__)


def _health_url(url: str) -> str:
    return url.rstrip("/mcp").rstrip("/") + "/"


async def _is_alive(url: str, timeout: float = 2.0) -> bool:
    import httpx

    try:
        async with httpx.AsyncClient() as cli:
            r = await cli.get(_health_url(url), timeout=timeout)
            return r.status_code < 500  # 200/404/405 都算活
    except Exception:
        return False


async def _spawn_and_wait(server: MCPServer, wait_seconds: int = 20) -> bool:
    cmd = list(server.startup_command or [])
    if not cmd:
        return False
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=server.startup_cwd or None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # 脱离 backend 父进程
        )
    except FileNotFoundError:
        logger.warning("[mcp-autostart] %s startup_command 可执行文件不存在：%s", server.name, cmd)
        return False
    except Exception:  # noqa: BLE001
        logger.exception("[mcp-autostart] %s spawn 失败", server.name)
        return False

    logger.info("[mcp-autostart] spawned %s pid=%s", server.name, proc.pid)
    if not server.url:
        return True  # 无 url 不做 health check
    deadline = asyncio.get_event_loop().time() + max(2, min(int(wait_seconds), 60))
    while asyncio.get_event_loop().time() < deadline:
        if await _is_alive(server.url):
            logger.info("[mcp-autostart] %s 健康检查通过", server.name)
            return True
        await asyncio.sleep(1)
    logger.warning(
        "[mcp-autostart] %s spawned 但 %ds 内 %s 仍不可达",
        server.name, wait_seconds, _health_url(server.url),
    )
    return False


async def autostart_local_mcp_servers(db: AsyncSession, *, wait_seconds: int = 20) -> dict:
    """对所有「is_enabled + http + 有 startup_command」的 MCPServer 探活并按需拉起。

    返回 {started: [...], reused: [...], failed: [...]} 便于日志/测试。best-effort。
    """
    result: dict[str, list[str]] = {"started": [], "reused": [], "failed": []}
    try:
        servers = (
            await db.execute(
                select(MCPServer).where(
                    MCPServer.is_enabled.is_(True),
                    MCPServer.server_type == "http",
                )
            )
        ).scalars().all()
    except Exception:  # noqa: BLE001
        logger.exception("[mcp-autostart] 查询 MCPServer 失败")
        return result

    for s in servers:
        if not s.startup_command:
            continue  # 远程 / 无启动命令的 http MCP 不归我们管
        if s.url and await _is_alive(s.url):
            result["reused"].append(s.name)
            continue
        ok = await _spawn_and_wait(s, wait_seconds=wait_seconds)
        result["started" if ok else "failed"].append(s.name)

    if any(result.values()):
        logger.info(
            "[mcp-autostart] 完成：started=%s reused=%s failed=%s",
            result["started"], result["reused"], result["failed"],
        )
    return result
