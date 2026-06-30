"""M6: Admin 端 ClawHub 搜索 / 安装 / 卸载 API。

人工路径：与 InstallerAgent 走的是同一个 `remote_skill_installer.install`，
所以 UI 安装 ≡ Agent 安装，效果一致。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.core.deps import AdminUser, DBSession
from app.services import clawhub_client, remote_skill_installer

router = APIRouter(prefix="/api/admin/clawhub", tags=["clawhub"])


class ClawhubSearchResp(BaseModel):
    ok: bool
    query: str
    results: list | dict


class ClawhubInspectResp(BaseModel):
    ok: bool
    slug: str
    version: str
    blocked: bool
    high_risk_tags: list[str]
    skill: dict
    security: dict


class ClawhubInstallReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    version: str | None = None
    mission_id: uuid.UUID | None = None
    force_high_risk: bool = False


class ClawhubInstallResp(BaseModel):
    ok: bool
    install_id: uuid.UUID | None = None
    local_skill_id: uuid.UUID | None = None
    runtime_kind: str | None = None
    install_dir: str | None = None
    entrypoint: str | None = None
    capability_tags: list[str] = []
    error: str | None = None
    needs_approval: bool = False
    blocked: bool = False


class InstalledItem(BaseModel):
    install_id: uuid.UUID
    slug: str
    version: str
    runtime_kind: str
    install_dir: str
    capability_tags: list[str]
    local_skill_id: uuid.UUID | None = None
    installed_at: str


@router.get("/search", response_model=ClawhubSearchResp)
async def search(query: str, _: AdminUser, limit: int = 20) -> ClawhubSearchResp:
    try:
        data = await clawhub_client.search_skills(query, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"clawhub: {exc}") from exc
    results = data.get("results") or data.get("items") or data
    return ClawhubSearchResp(ok=True, query=query, results=results)


@router.get("/inspect", response_model=ClawhubInspectResp)
async def inspect(slug: str, _: AdminUser, version: str | None = None) -> ClawhubInspectResp:
    try:
        info = await remote_skill_installer.inspect(slug, version)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ClawhubInspectResp(
        ok=True,
        slug=info["slug"],
        version=info["version"],
        blocked=info["blocked"],
        high_risk_tags=info["high_risk_tags"],
        skill=info["skill"],
        security=info["security"],
    )


@router.post("/install", response_model=ClawhubInstallResp)
async def install(
    payload: ClawhubInstallReq, _: AdminUser, db: DBSession
) -> ClawhubInstallResp:
    try:
        rec = await remote_skill_installer.install(
            db,
            slug=payload.slug,
            version=payload.version,
            mission_id=payload.mission_id,
            force_high_risk=payload.force_high_risk,
        )
    except remote_skill_installer.ClawhubInstallNeedsApproval as exc:
        return ClawhubInstallResp(ok=False, needs_approval=True, error=str(exc))
    except remote_skill_installer.ClawhubInstallBlocked as exc:
        return ClawhubInstallResp(ok=False, blocked=True, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        return ClawhubInstallResp(ok=False, error=str(exc))
    return ClawhubInstallResp(
        ok=True,
        install_id=rec.id,
        local_skill_id=rec.local_skill_id,
        runtime_kind=rec.runtime_kind,
        install_dir=rec.install_dir,
        entrypoint=rec.entrypoint,
        capability_tags=rec.capability_tags,
    )


@router.delete("/install/{install_id}", status_code=status.HTTP_204_NO_CONTENT)
async def uninstall(install_id: uuid.UUID, _: AdminUser, db: DBSession) -> None:
    ok = await remote_skill_installer.uninstall(db, install_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="install_id 不存在")


@router.get("/installed", response_model=list[InstalledItem])
async def list_installed(
    _: AdminUser,
    db: DBSession,
    mission_id: uuid.UUID | None = None,
) -> list[InstalledItem]:
    rows = await remote_skill_installer.list_installed(db, mission_id=mission_id)
    return [
        InstalledItem(
            install_id=r.id,
            slug=r.clawhub_slug,
            version=r.clawhub_version,
            runtime_kind=r.runtime_kind,
            install_dir=r.install_dir,
            capability_tags=r.capability_tags,
            local_skill_id=r.local_skill_id,
            installed_at=r.installed_at.isoformat(),
        )
        for r in rows
    ]
