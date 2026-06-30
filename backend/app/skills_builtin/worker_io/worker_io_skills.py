"""v3 · Worker 输出契约（return_result）。

worker 不再写 workspace artifacts；调用 return_result(...) 把最终结果直接交付给 caller super。
非文本（image/pdf/video）通过 artifact_bytes_b64 自动上传 S3 + 返回 URL。
worker 也可拒收任务（needs_clarification=True）反问 super 补全输入。
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid as _uuid

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)

MAX_ARTIFACT_BYTES = 100 * 1024 * 1024  # V18: 100MB cap
MAX_TEXT_RETURN = 200_000  # 200KB text


class ReturnResultArgs(BaseModel):
    text: str | None = Field(default=None, description="文本最终结果")
    structured: dict | None = Field(default=None, description="结构化结果 JSON")
    artifact_bytes_b64: str | None = Field(default=None, description="非文本产物（base64）→ 自动 S3")
    artifact_url: str | None = Field(default=None, description="已上传过 S3 的产物直接传 URL")
    media_type: str = Field(default="", description="配合 artifact_*；如 image/png / application/pdf")
    needs_clarification: bool = Field(
        default=False, description="True = 拒收当前任务，要 super 补信息"
    )
    clarification_questions: list[str] = Field(
        default_factory=list, description="具体要 super 补什么"
    )
    suggested_super_actions: list[str] = Field(
        default_factory=list, description="建议 super 做什么再来调"
    )
    partial_progress: dict | None = Field(
        default=None, description="已完成多少（便于 super 决定继续 vs 放弃）"
    )


def return_result_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _return(
        text: str | None = None,
        structured: dict | None = None,
        artifact_bytes_b64: str | None = None,
        artifact_url: str | None = None,
        media_type: str = "",
        needs_clarification: bool = False,
        clarification_questions: list[str] | None = None,
        suggested_super_actions: list[str] | None = None,
        partial_progress: dict | None = None,
    ) -> str:
        """Worker 输出契约 v2：直接 return 结果给调用 super。返回值是 JSON 字符串，
        invoke_worker 在 super 侧解析后再返回给 super LLM。"""
        # V36 互斥 → v7.6 改为软兜底：模型（qwen 等）偶发同时给 needs_clarification 与 text，
        # 旧版 raise ValueError 会让整个 worker invocation 崩溃 → super 误判 worker 故障升级。
        # 现改为：保留 needs_clarification 语义（worker 被阻塞是更强信号），把已产出的 text
        # 折进 clarification_questions 不丢，不再 raise。
        has_result = bool(text or structured or artifact_bytes_b64 or artifact_url)
        clarification_questions = clarification_questions or []
        if needs_clarification and has_result:
            logger.warning(
                "[return_result] needs_clarification 与 result 同时给出 → 软兜底：保留 clarification，"
                "text 折入提问；不再 raise"
            )
            if text:
                clarification_questions = clarification_questions + [
                    f"（worker 附带产出，供参考）{text[:500]}"
                ]
            # 丢弃实际结果字段，避免 super 拿到半成品当成功
            text = None
            structured = None
            artifact_bytes_b64 = None
            artifact_url = None
        suggested_super_actions = suggested_super_actions or []

        envelope: dict = {
            "ok": True,
            "status": "needs_clarification" if needs_clarification else "completed",
            "worker_agent_id": str((ctx.extra or {}).get("agent_id") or ""),
            "ts": time.time(),
        }

        if text:
            envelope["text"] = text[:MAX_TEXT_RETURN]
        if structured is not None:
            envelope["structured"] = structured

        # V18：artifact 上限（admin 可调，默认 100MB）
        if artifact_bytes_b64:
            try:
                raw = base64.b64decode(artifact_bytes_b64, validate=False)
            except Exception as exc:
                raise ValueError(f"❌ artifact_bytes_b64 不是合法 base64：{exc}") from exc
            # 读 admin 可调上限
            from app.core import system_settings as _ss
            if ctx.db_factory is not None:
                async with ctx.db_factory() as _db_cfg:
                    cap_mb = await _ss.get_int(_db_cfg, "return_result.artifact_bytes_max_mb", MAX_ARTIFACT_BYTES // (1024 * 1024))
            else:
                cap_mb = MAX_ARTIFACT_BYTES // (1024 * 1024)
            cap_bytes = cap_mb * 1024 * 1024
            if len(raw) > cap_bytes:
                raise ValueError(
                    f"❌ artifact 大小 {len(raw)} > {cap_bytes} 上限（{cap_mb}MB / V18）；"
                    "请改用 s3_upload skill 自己上传后传 artifact_url"
                )
            # 上传 S3
            from app.services.storage_service import get_storage
            store = get_storage()
            ext = (media_type or "application/octet-stream").rsplit("/", 1)[-1] or "bin"
            if "+" in ext:
                ext = ext.split("+", 1)[0]
            key = f"worker_return/{(ctx.extra or {}).get('agent_id') or 'unknown'}/{_uuid.uuid4().hex}.{ext[:20]}"
            try:
                url = await store.upload(
                    key, raw, content_type=media_type or "application/octet-stream"
                )
                envelope["artifact_url"] = url
                envelope["artifact_bytes"] = len(raw)
                envelope["media_type"] = media_type or "application/octet-stream"
            except Exception as exc:
                logger.exception("[return_result] S3 上传失败")
                raise ValueError(f"❌ S3 上传失败：{exc}") from exc
        elif artifact_url:
            envelope["artifact_url"] = artifact_url
            envelope["media_type"] = media_type or ""

        if needs_clarification:
            envelope["clarification_questions"] = clarification_questions[:10]
            envelope["suggested_super_actions"] = suggested_super_actions[:10]
            if partial_progress is not None:
                envelope["partial_progress"] = partial_progress

        logger.info(
            "📊 colony_v3_return_result worker=%s status=%s text_chars=%d has_artifact=%s",
            envelope.get("worker_agent_id"),
            envelope["status"],
            len(envelope.get("text") or ""),
            bool(envelope.get("artifact_url")),
        )
        return json.dumps(envelope, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_return,
        name="return_result",
        description=(
            "（worker 专用）Worker 最终输出。**调用即结束 worker turn**。\n"
            "参数（任选）：\n"
            "- text(str)：文本最终结果\n"
            "- structured(dict)：结构化 JSON\n"
            "- artifact_bytes_b64(str) + media_type：非文本产物（≤100MB），自动上传 S3 + 返回 artifact_url\n"
            "- artifact_url(str)：已上传过的 S3 URL\n"
            "- needs_clarification(bool)：True = 拒收任务，要 super 补；与 text/structured/artifact 互斥\n"
            "- clarification_questions(list[str])：具体问 super 什么\n"
            "- suggested_super_actions(list[str])：建议 super 先做什么再来调\n"
            "- partial_progress(dict)：已完成多少（可选）"
        ),
    )
