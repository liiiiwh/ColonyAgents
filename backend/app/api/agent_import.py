"""ADR-019 D3 · 一键导入外部 worker（agency-agents）的 API。

- GET  /api/agent-import/catalog?version=en|zh — 列源仓库可导入的 agent
- POST /api/agent-import/preview {version, path} — 预览 persona→worker 映射（不写库）
- POST /api/agent-import {version, path}         — 导入（按 capability 幂等 upsert）

外部 prompt 当数据处理，绝不执行其指令（prompt-injection 警觉）。导入物 model_id=NULL
（用平台默认模型，ADR-017），category='worker.imported'。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import AdminUser, DBSession
from app.domain import import_source as imp

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent-import", tags=["agent-import"])


def _require_version(version: str) -> None:
    if not imp.is_supported_version(version):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"version 必须是 {'/'.join(imp.SUPPORTED_VERSIONS)}（en=英文原仓库，zh=社区中文 fork）",
        )


@router.get("/catalog")
async def catalog(version: str, _: AdminUser) -> dict:
    """列某版本（仓库）下所有可导入 agent。"""
    _require_version(version)
    try:
        items = await imp.fetch_catalog(version)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"拉取 catalog 失败：{exc}")
    return {
        "version": version,
        "repo": imp.REPOS[version][0],
        "count": len(items),
        "items": items,
    }


class ImportBody(BaseModel):
    version: str
    path: str


async def _fetch_spec(version: str, path: str) -> dict:
    try:
        md, sha = await imp.fetch_agent_markdown(version, path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"拉取 agent 失败：{exc}")
    parsed = imp.parse_agent_markdown(md)
    return imp.to_worker_spec(parsed, version=version, path=path, sha=sha)


@router.post("/preview")
async def preview(body: ImportBody, _: AdminUser) -> dict:
    """预览映射结果（不写库），供前端确认导入前查看。"""
    _require_version(body.version)
    return {"spec": await _fetch_spec(body.version, body.path)}


@router.post("")
async def do_import(body: ImportBody, _: AdminUser, db: DBSession) -> dict:
    """导入为 worker（按 capability 幂等：已存在 → 更新人格/协议/溯源）。"""
    _require_version(body.version)
    spec = await _fetch_spec(body.version, body.path)

    from app.models.agent import Agent
    from app.schemas.agent import AgentCreate
    from app.services import agent_service

    existing = (await db.execute(
        select(Agent).where(Agent.kind == "worker", Agent.capability == spec["capability"])
    )).scalar_one_or_none()
    if existing is not None:
        existing.name = spec["name"]
        existing.soul_md = spec["soul_md"]
        existing.protocol_md = spec["protocol_md"]
        existing.description = spec["description"]
        existing.category = "worker.imported"
        existing.extra_config = spec["extra_config"]
        await db.commit()
        return {
            "ok": True, "agent_id": str(existing.id), "updated": True,
            "capability": spec["capability"], "name": spec["name"],
        }

    payload = AgentCreate(
        name=spec["name"], kind="worker", capability=spec["capability"],
        category="worker.imported", soul_md=spec["soul_md"], protocol_md=spec["protocol_md"],
        description=spec["description"], model_id=None, extra_config=spec["extra_config"],
    )
    try:
        agent = await agent_service.create_agent(db, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {
        "ok": True, "agent_id": str(agent.id), "updated": False,
        "capability": spec["capability"], "name": spec["name"],
    }
