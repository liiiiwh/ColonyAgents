"""MCP Server CRUD + 连接测试。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.deps import AdminUser, DBSession
from app.schemas.skill import (
    MCPServerCreate,
    MCPServerPublic,
    MCPServerUpdate,
    MCPTestResponse,
)
from app.services import skill_service

router = APIRouter(prefix="/api/mcp-servers", tags=["mcp-servers"])


@router.get("", response_model=list[MCPServerPublic])
async def list_mcp_servers(_: AdminUser, db: DBSession) -> list[MCPServerPublic]:
    items = await skill_service.list_mcp_servers(db)
    return [MCPServerPublic.model_validate(s) for s in items]


@router.post("", response_model=MCPServerPublic, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    payload: MCPServerCreate, _: AdminUser, db: DBSession
) -> MCPServerPublic:
    _validate_transport(payload.server_type, payload.command, payload.url)
    server = await skill_service.create_mcp_server(db, payload)
    return MCPServerPublic.model_validate(server)


@router.get("/{server_id}", response_model=MCPServerPublic)
async def get_mcp_server(server_id: uuid.UUID, _: AdminUser, db: DBSession) -> MCPServerPublic:
    server = await skill_service.get_mcp_server(db, server_id)
    if not server:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="mcp server 不存在")
    return MCPServerPublic.model_validate(server)


@router.put("/{server_id}", response_model=MCPServerPublic)
async def update_mcp_server(
    server_id: uuid.UUID,
    payload: MCPServerUpdate,
    _: AdminUser,
    db: DBSession,
) -> MCPServerPublic:
    server = await skill_service.get_mcp_server(db, server_id)
    if not server:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="mcp server 不存在")
    updated = await skill_service.update_mcp_server(db, server, payload)
    return MCPServerPublic.model_validate(updated)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(server_id: uuid.UUID, _: AdminUser, db: DBSession) -> None:
    server = await skill_service.get_mcp_server(db, server_id)
    if not server:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="mcp server 不存在")
    await skill_service.delete_mcp_server(db, server)


@router.post("/{server_id}/test", response_model=MCPTestResponse)
async def test_mcp_server(server_id: uuid.UUID, _: AdminUser, db: DBSession) -> MCPTestResponse:
    server = await skill_service.get_mcp_server(db, server_id)
    if not server:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="mcp server 不存在")
    reachable, err, tools = await skill_service.test_mcp_server(server)
    return MCPTestResponse(reachable=reachable, error=err, tools=tools)


def _validate_transport(server_type: str, command: list[str] | None, url: str | None) -> None:
    if server_type == "stdio" and not command:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="stdio MCP 必须提供 command 数组",
        )
    if server_type == "http" and not url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="http MCP 必须提供 url")
