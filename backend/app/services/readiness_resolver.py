"""ADR-010 R2 · ensure_ready resolver。

走 MCP 的 readiness_manifest，对每个 requirement：probe → 未满足则按 kind 派发：
- auto-shell → remediate（跑 run_shell）→ 重新 probe；
- human-*/instructions → 收进 pending（需人工介入，交 R4 人类残留卡 + 暂停/恢复）。
probe_fn / remediate_fn 注入；真实版在 R5 接线。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.readiness import ReadinessManifest
from app.models.skill import MCPServer

logger = logging.getLogger(__name__)

_HUMAN_KINDS = {"human-qr", "human-secret", "human-tos", "instructions"}


async def ensure_ready(
    db: AsyncSession,
    mcp_server_id,
    *,
    probe_fn,
    remediate_fn=None,
) -> dict:
    """返回 {ready, satisfied:[id], actions_taken:[id], pending:[{id,kind}]}。

    ready=True 仅当所有 requirement 探针通过。有 human-* 未满足 → pending（不阻塞，交 R4）。
    """
    sid = mcp_server_id if isinstance(mcp_server_id, uuid.UUID) else uuid.UUID(str(mcp_server_id))
    server = await db.get(MCPServer, sid)
    if server is None:
        return {"ready": False, "error": "mcp_server 不存在", "pending": [], "satisfied": [], "actions_taken": []}

    manifest = ReadinessManifest.from_dict(server.readiness_manifest or {})
    satisfied: list[str] = []
    actions_taken: list[str] = []
    pending: list[dict] = []

    for req in manifest.requirements:
        rd = {"id": req.id, "kind": req.kind, "probe": req.probe, "remediation": req.remediation}
        if await probe_fn(rd, server):
            satisfied.append(req.id)
            continue
        # 未满足
        if req.kind == "auto-shell" and remediate_fn is not None:
            ok = await remediate_fn(rd, server)
            if ok and await probe_fn(rd, server):
                actions_taken.append(req.id)
                satisfied.append(req.id)
                continue
            pending.append({"id": req.id, "kind": req.kind})
        elif req.kind in _HUMAN_KINDS:
            pending.append({"id": req.id, "kind": req.kind})
        else:
            pending.append({"id": req.id, "kind": req.kind})

    return {
        "ready": len(pending) == 0,
        "satisfied": satisfied,
        "actions_taken": actions_taken,
        "pending": pending,
    }
