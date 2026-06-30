"""Workspace 写入服务：把 Agent 交付物上传 S3 并返回带 URL 的 artifact（ADR-027 D3）。

ADR-027：退役 by-node workspace 簿记（mission.workspace[node_name]）。交付物只活在
S3 + data-artifact 事件 + worker thread；S3 key 按 mission_id + worker capability + label
归档（不再按 node_name）。本服务只负责上传 S3 + 填回 s3_key/s3_url，不再改 mission.workspace。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.mission import Mission
from app.schemas.message import Artifact

logger = logging.getLogger(__name__)


def _slugify_segment(value: str) -> str:
    """把任意字符串收敛成安全的 S3 路径段（小写 / 仅 [a-z0-9_-] / 去空）。"""
    import re as _re

    s = (value or "").strip().lower()
    s = _re.sub(r"[^a-z0-9_-]+", "-", s).strip("-")
    return s or "default"


def _workspace_key(
    *,
    mission_id: uuid.UUID,
    capability: str,
    label: str,
    artifact_id: uuid.UUID,
    media_type: str,
) -> str:
    """生成 S3 Key：colony/workspace/{mission_id}/{capability}/{label}-{artifact_id}.<ext>

    ADR-027 D3：按 mission_id + worker capability + label 归档（不再按 node_name）。
    """
    ext_map = {
        "text/markdown": "md",
        "text/plain": "txt",
        "application/json": "json",
        "text/html": "html",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
    }
    # 精确匹配优先；再按大类兜底（image/* → png，text/* → txt）
    ext = ext_map.get(media_type)
    if not ext:
        top = (media_type or "").split("/", 1)[0].lower()
        ext = {"image": "png", "text": "txt", "application": "bin"}.get(top, "bin")
    cap = _slugify_segment(capability)
    lbl = _slugify_segment(label)
    return f"colony/workspace/{mission_id}/{cap}/{lbl}-{artifact_id}.{ext}"


async def write_artifact(
    db: AsyncSession,
    mission: Mission,
    artifact: Artifact,
    *,
    capability: str = "default",
    is_deliverable: bool = True,
) -> Artifact:
    """上传交付物到 S3 并填回 s3_key / s3_url（ADR-027 D3）。

    行为依 `is_deliverable` 分叉：

    **is_deliverable=True（交付物）**
    - 产物内容上传 S3，key 规范：
      `colony/workspace/{mission_id}/{capability}/{label}-{artifact_id}.<ext>`
    - 返回的 artifact 带 s3_key / s3_url
    - 调用方随后可通过 event_queue 推送 data-artifact 事件

    **is_deliverable=False（中间态 / 过程数据）**
    - **不**上传 S3，原样返回（内容留在 worker thread，供后续上下文加载消费）

    ADR-027：不再写 `mission.workspace[node_name]`。若 `artifact.s3_key` / `s3_url`
    已由调用方预填（如 invoke_aux_model 图片已上传），沿用不覆盖。
    """
    from app.services.storage_service import get_storage

    if is_deliverable and not artifact.s3_key and not artifact.s3_url and artifact.content:
        try:
            key = _workspace_key(
                mission_id=mission.id,
                capability=capability,
                label=artifact.label,
                artifact_id=artifact.id,
                media_type=artifact.media_type or "text/plain",
            )
            body = artifact.content.encode("utf-8")
            storage = get_storage()
            await storage.upload(key, body, content_type=artifact.media_type or "text/plain")
            artifact.s3_key = key
            try:
                artifact.s3_url = await storage.presigned_url(
                    key, expires_in=settings.S3_ARTIFACT_URL_EXPIRE
                )
            except Exception:
                artifact.s3_url = None
        except Exception:
            logger.exception("workspace artifact 上传 S3 失败，降级为仅保留 content")
    return artifact


async def write_artifacts_batch(
    db: AsyncSession,
    mission: Mission,
    artifacts: list[Artifact],
    *,
    capability: str = "default",
) -> list[Artifact]:
    """**批量** 上传多个交付物到 S3（ADR-027 D3）。

    与 `write_artifact` 一致，只是一次写入多条 —— 适合 Meshy 3D 任务这种一次产出多文件
    （GLB / 缩略图 / 视频 / 纹理）的场景。

    每条 artifact 若已带 `s3_key` 或 `s3_url`，沿用；否则按 content + media_type 上传 S3
    并填回 `s3_key` / `s3_url`（前提 content 非空）。不再写 mission.workspace。
    """
    from app.services.storage_service import get_storage

    storage = get_storage()
    out_artifacts: list[Artifact] = []
    for art in artifacts:
        if not art.s3_key and not art.s3_url and art.content:
            try:
                key = _workspace_key(
                    mission_id=mission.id,
                    capability=capability,
                    label=art.label,
                    artifact_id=art.id,
                    media_type=art.media_type or "application/octet-stream",
                )
                # content 是文本（base64 编码的二进制 / 纯文本 / 注释）→ 编码为 bytes
                body = art.content.encode("utf-8") if isinstance(art.content, str) else b""
                await storage.upload(
                    key, body, content_type=art.media_type or "application/octet-stream"
                )
                art.s3_key = key
                try:
                    art.s3_url = await storage.presigned_url(
                        key, expires_in=settings.S3_ARTIFACT_URL_EXPIRE
                    )
                except Exception:
                    art.s3_url = None
            except Exception:
                logger.exception("workspace artifacts_batch S3 上传失败 label=%s", art.label)
        out_artifacts.append(art)
    return out_artifacts
