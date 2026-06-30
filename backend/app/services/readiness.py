"""ADR-010 R2/R4/R5 wiring · 真实 probe / remediate + ensure_ready_for_server 编排。

- default_probe：http_health（探活）/ env_present（查密钥）/ mcp_tool（调 MCP 工具，如
  check_login_status）。
- default_remediate：server_up 用 startup_command spawn（受信任的已装命令；复用 mcp_autostart
  的拉起+健康检查）；其它 auto-shell 走 run_shell+门（execute_guarded_shell）。
- ensure_ready_for_server：装时主动 / 运行时反应都调它。pending 的 human-* → 建卡 + 暂停项目
  （非阻塞，复用 approval 通道 + paused_waiting_capability，reason 前缀 readiness:）。
"""
from __future__ import annotations

import logging
import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.human_action import build_human_action_card
from app.models.skill import MCPServer
from app.services.mcp_autostart import _is_alive, _spawn_and_wait
from app.services.readiness_resolver import ensure_ready

logger = logging.getLogger(__name__)


async def default_probe(req: dict, server: MCPServer) -> bool:
    """据 requirement.probe.type 做具体检查。未知类型保守返回 False（→ 走 pending）。"""
    probe = req.get("probe") or {}
    ptype = probe.get("type")

    if ptype == "http_health":
        return bool(server.url) and await _is_alive(server.url)

    if ptype == "env_present":
        key = probe.get("key") or ""
        if key in (server.env_vars or {}) and (server.env_vars or {}).get(key):
            return True
        return bool(os.environ.get(key))

    if ptype == "mcp_tool":
        return await _probe_mcp_tool(server, probe.get("tool") or "check_login_status")

    return False


async def _probe_mcp_tool(server: MCPServer, tool_name: str) -> bool:
    """连 MCP 调一个只读探针工具（如 check_login_status），解释返回判断是否满足。"""
    if not server.url:
        return False
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(
            {server.name: {"url": server.url, "transport": "streamable_http",
                           "headers": server.headers or {}}}
        )
        tools = await client.get_tools()
        target = next((t for t in tools if t.name == tool_name or t.name.endswith(tool_name)), None)
        if target is None:
            return False
        result = await target.ainvoke({})
        text = str(result).lower()
        # 朴素判断：包含 true/logged/已登录 视为已登录；包含 false/not/未 视为未登录
        if any(k in text for k in ("not logged", "未登录", "false", "require login", "需要登录")):
            return False
        return any(k in text for k in ("logged_in", "true", "已登录", "登录成功", '"islogin": true'))
    except Exception:  # noqa: BLE001
        logger.warning("[readiness] mcp_tool 探针失败 server=%s tool=%s", server.name, tool_name)
        return False


async def default_remediate(req: dict, server: MCPServer) -> bool:
    """auto-shell 补救。server_up：用 startup_command 拉起（受信任已装命令）。"""
    rid = req.get("id")
    if rid == "server_up" or (req.get("remediation") or {}).get("source") == "startup_command":
        if not server.startup_command:
            return False
        return await _spawn_and_wait(server)
    # 其它 auto-shell 暂不在此自动跑（需 run_shell+门 + 发起 agent 上下文）→ 交 pending/Builder
    return False


async def ensure_ready_for_server(
    db: AsyncSession,
    mcp_server_id,
    *,
    mission_id=None,
    post_human_action=None,
) -> dict:
    """装时主动 / 运行时反应都调它：自动补救 auto-shell；human-* pending → 建卡+暂停。

    post_human_action(server, requirement) 注入便于独测；默认用 _post_and_pause。
    """
    res = await ensure_ready(db, mcp_server_id, probe_fn=default_probe, remediate_fn=default_remediate)
    pending_human = [p for p in res.get("pending", []) if p["kind"] != "auto-shell"]
    if pending_human and mission_id is not None:
        sid = mcp_server_id if isinstance(mcp_server_id, uuid.UUID) else uuid.UUID(str(mcp_server_id))
        server = await db.get(MCPServer, sid)
        poster = post_human_action or _post_and_pause
        for p in pending_human:
            await poster(db, mission_id, server, p)
    return res


async def _post_and_pause(db, mission_id, server: MCPServer, requirement: dict) -> None:
    """建人类残留卡（复用 approval 通道）+ 把项目暂停（readiness: 前缀）。"""
    qr_url = None
    if requirement.get("kind") == "human-qr":
        qr_url = await _fetch_qr_url(server)
    card = build_human_action_card(requirement, server_name=server.name, qr_image_url=qr_url)
    # 幂等：同项目已有同标题的 pending 卡 → 不重复发（re-finalize / re-probe 不刷屏）
    try:
        from sqlalchemy import text as _text
        _pid = mission_id if isinstance(mission_id, uuid.UUID) else uuid.UUID(str(mission_id))
        dup = (await db.execute(_text(
            "SELECT 1 FROM pending_approvals WHERE mission_id=:p AND title=:t AND status='pending' LIMIT 1"
        ), {"p": str(_pid), "t": card["title"]})).first()
        if dup:
            logger.info("[readiness] 同标题 pending 卡已存在，跳过重复发：%s", card["title"])
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services import pending_approval_service as pa

        await pa.create_pending(
            db,
            mission_id=mission_id if isinstance(mission_id, uuid.UUID) else uuid.UUID(str(mission_id)),
            title=card["title"], message=card["body"], options=card["options"],
        )
    except Exception:  # noqa: BLE001
        logger.exception("[readiness] 建人类残留卡失败")
    # 暂停项目，等人类完成 → resume 复验
    try:
        from app.models.mission import Mission

        _pid2 = mission_id if isinstance(mission_id, uuid.UUID) else uuid.UUID(str(mission_id))
        proj = await db.get(Mission, _pid2)
        if proj is not None:
            proj.lifecycle_status = "paused_waiting_capability"
            proj.paused_reason = f"readiness:{server.name}:{requirement['id']} 需人工介入（{requirement['kind']}）"
            await db.commit()
            # ADR-028 D4 · H1 · 缺能力/扫码人工门落卡 → 硬停当前 tick（cooperative；幂等）。
            try:
                from app.services import super_inbox
                await super_inbox.cancel_current_tick(_pid2)
            except Exception:  # noqa: BLE001
                logger.exception("[readiness] H1 cancel_current_tick 失败（不阻塞）")
    except Exception:  # noqa: BLE001
        logger.exception("[readiness] 暂停项目失败")


async def _fetch_qr_url(server: MCPServer) -> str | None:
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(
            {server.name: {"url": server.url, "transport": "streamable_http",
                           "headers": server.headers or {}}}
        )
        tools = await client.get_tools()
        t = next((x for x in tools if x.name.endswith("get_login_qrcode")), None)
        if t is None:
            return None
        res = await t.ainvoke({})
        return _extract_qr_image(res)
    except Exception:  # noqa: BLE001
        return None


def _extract_qr_image(res) -> str | None:
    """从 MCP get_login_qrcode 返回里抽二维码图：优先 https url，其次 base64 image block → data URI。

    xhs-mcp 返回 content list 含 {'type':'image','base64':'iVBOR...'}（PNG base64），不是 url。
    """
    import re

    # content-block list（langchain MCP 常见形态）
    blocks = res if isinstance(res, list) else None
    if blocks:
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "image" and b.get("base64"):
                mt = b.get("mimeType") or b.get("media_type") or "image/png"
                return f"data:{mt};base64,{b['base64']}"
    s = str(res)
    m = re.search(r"https?://\S+\.(png|jpg|jpeg)", s)
    if m:
        return m.group(0)
    # 兜底：字符串形态里的 'base64': '....'
    m2 = re.search(r"['\"]base64['\"]\s*:\s*['\"]([A-Za-z0-9+/=]{40,})['\"]", s)
    if m2:
        return f"data:image/png;base64,{m2.group(1)}"
    return None
