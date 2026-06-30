"""ADR-027 · workspace_service 退役 by-node 簿记。

交付物只活在 S3 + data-artifact 事件 + worker thread；S3 key 按
mission_id + worker capability + label 归档（不再按 node_name）。
write_artifact / write_artifacts_batch 只上传 S3 + 填回 s3_key/s3_url，
不再写 mission.workspace[node]。
"""

from __future__ import annotations

import uuid

import pytest

from app.models.agent import Agent
from app.models.mission import Mission
from app.models.user import User
from app.schemas.message import Artifact
from app.services import workspace_service
from app.services.storage_service import make_inmemory_backend, set_storage

pytestmark = pytest.mark.asyncio


async def _mk_mission(db) -> Mission:
    u = User(
        username=f"u-{uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:6]}@t.io",
        hashed_password="x",
    )
    db.add(u)
    await db.flush()
    ag = Agent(
        name=f"sup-{uuid.uuid4().hex[:6]}",
        category="custom",
        kind="super",
        model_id=None,
        soul_md="x",
        protocol_md="x",
    )
    db.add(ag)
    await db.flush()
    proj = Mission(
        name="m",
        slug=f"m-{uuid.uuid4().hex[:8]}",
        supervisor_agent_id=ag.id,
        created_by=u.id,
    )
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def test_write_artifact_uploads_s3_keyed_by_capability(db_session):
    """交付物上传 S3，key 按 mission_id + capability + label；不再写 mission.workspace。"""
    set_storage(make_inmemory_backend())
    try:
        mission = await _mk_mission(db_session)
        art = Artifact(type="text", label="r1", content="hello", media_type="text/plain")

        saved = await workspace_service.write_artifact(
            db_session, mission, art, capability="xhs_ops", is_deliverable=True
        )

        assert saved.s3_key, "交付物应上传 S3 并填回 s3_key"
        assert f"/{mission.id}/xhs_ops/" in saved.s3_key, saved.s3_key
        # by-node workspace 已退役：mission.workspace 不被写
        await db_session.refresh(mission, attribute_names=["workspace"])
        assert mission.workspace == {}
    finally:
        set_storage(None)  # type: ignore[arg-type]


async def test_write_artifact_non_deliverable_not_uploaded(db_session):
    """中间态（is_deliverable=False）不上传 S3，原样返回。"""
    set_storage(make_inmemory_backend())
    try:
        mission = await _mk_mission(db_session)
        art = Artifact(type="text", label="draft", content="wip", media_type="text/plain")

        saved = await workspace_service.write_artifact(
            db_session, mission, art, capability="xhs_ops", is_deliverable=False
        )

        assert not saved.s3_key
    finally:
        set_storage(None)  # type: ignore[arg-type]


async def test_write_artifacts_batch_uploads_all(db_session):
    """批量交付物逐条上传 S3 并填回 s3_key；不再写 mission.workspace。"""
    set_storage(make_inmemory_backend())
    try:
        mission = await _mk_mission(db_session)
        arts = [
            Artifact(type="text", label=f"a{i}", content=f"c{i}", media_type="text/plain")
            for i in range(3)
        ]

        saved = await workspace_service.write_artifacts_batch(
            db_session, mission, arts, capability="deliver"
        )

        assert len(saved) == 3
        assert all(a.s3_key for a in saved)
        await db_session.refresh(mission, attribute_names=["workspace"])
        assert mission.workspace == {}
    finally:
        set_storage(None)  # type: ignore[arg-type]
