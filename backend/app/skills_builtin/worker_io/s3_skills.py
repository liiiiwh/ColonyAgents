"""S3 工具族：上传 / 下载 / 列出对象。

通过 `storage_service.get_storage()` 统一获取当前后端（生产 S3Backend，
测试 InMemoryBackend）。工具给 Agent 暴露轻量 API：上传文本、下载文本、列出 key。
二进制 / 大文件建议由 workspace_write 走高阶 artifact 接口。
"""

from __future__ import annotations

import logging

from langchain_core.tools import StructuredTool

from app.services.storage_service import get_storage
from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


def s3_upload_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _upload(
        key: str,
        content: str,
        content_type: str = "text/plain",
    ) -> str:
        storage = get_storage()
        data = content.encode("utf-8")
        try:
            await storage.upload(key, data, content_type=content_type)
        except Exception as exc:
            logger.exception("s3_upload failed")
            return f"❌ 上传失败：{exc}"
        logger.info("🪣 s3_upload: key=%s size=%d", key, len(data))
        return f"✅ 已上传 {key}（{len(data)} bytes，{content_type}）"

    return StructuredTool.from_function(
        coroutine=_upload,
        name="s3_upload",
        description=(
            "上传文本内容到对象存储。参数："
            "key(str，完整对象路径，如 sessions/abc/output.md)、"
            "content(str，文本内容)、"
            "content_type(str，默认 text/plain)。"
        ),
    )


def s3_download_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _download(key: str) -> str:
        storage = get_storage()
        try:
            data = await storage.download(key)
        except KeyError:
            return f"⚠️ 对象不存在：{key}"
        except Exception as exc:
            return f"❌ 下载失败：{exc}"
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return f"⚠️ 对象 {key} 是二进制（{len(data)} bytes），请使用 workspace_write 记录 s3_key"
        preview = text if len(text) <= 4000 else text[:4000] + "\n...(已截断)"
        return f"# 对象 {key}（{len(data)} bytes）\n\n{preview}"

    return StructuredTool.from_function(
        coroutine=_download,
        name="s3_download",
        description="从对象存储下载文本内容。参数：key(str)。",
    )


def s3_list_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _list(prefix: str = "") -> str:
        storage = get_storage()
        try:
            items = await storage.list_objects(prefix)
        except Exception as exc:
            return f"❌ 列表失败：{exc}"
        if not items:
            return f"⚠️ 前缀 {prefix!r} 下无对象"
        lines = [f"- {o['key']} ({o['size']} bytes @ {o['last_modified']})" for o in items[:50]]
        more = "" if len(items) <= 50 else f"\n... 共 {len(items)} 个，仅显示前 50"
        return "\n".join(lines) + more

    return StructuredTool.from_function(
        coroutine=_list,
        name="s3_list",
        description="列出对象存储中的对象。参数：prefix(str，前缀过滤，可选)。",
    )
