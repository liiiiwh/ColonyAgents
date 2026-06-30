"""fetch_url 工具：Agent 按需下载 HTTP(S) URL 内容并解析为文本。

- 最大 20MB，超限返回错误（不落盘，全部内存处理后释放）
- text/* / application/json / yaml / csv 等直接 UTF-8 解码
- image/* 不解析，返回 data URI（仅主 LLM 是多模态时才让它自己处理）
- PDF / Office 等二进制格式暂不支持，提示"请使用专门工具或先转为文本"
"""

from __future__ import annotations

import base64
import logging

import httpx
from langchain_core.tools import StructuredTool

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)

_MAX_BYTES = 20 * 1024 * 1024  # 20MB
_HTTP_TIMEOUT = 20.0

# 支持直接解码为 UTF-8 文本的 MIME 前缀 / 精确类型
_TEXT_PREFIXES = ("text/",)
_TEXT_EXACT = {
    "application/json",
    "application/yaml",
    "application/x-yaml",
    "application/xml",
    "application/x-ndjson",
    "application/csv",
    "application/x-sh",
    "application/javascript",
    "application/x-python",
}


def _is_texty(media_type: str | None) -> bool:
    if not media_type:
        return False
    mt = media_type.split(";", 1)[0].strip().lower()
    if any(mt.startswith(p) for p in _TEXT_PREFIXES):
        return True
    return mt in _TEXT_EXACT


async def fetch_url_content(url: str) -> tuple[bytes, str]:
    """HTTP GET 拉 URL，返回 (body, content_type)。超限抛 ValueError。"""
    async with (
        httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True, trust_env=False) as client,
        client.stream("GET", url) as resp,
    ):
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "application/octet-stream")
        body = bytearray()
        async for chunk in resp.aiter_bytes():
            body.extend(chunk)
            if len(body) > _MAX_BYTES:
                raise ValueError(f"文件超过 20MB (已下载 {len(body)} bytes)")
    return bytes(body), ctype


def fetch_url_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _fetch(url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return "❌ url 必须以 http:// 或 https:// 开头"
        try:
            body, ctype = await fetch_url_content(url)
        except ValueError as exc:
            return f"❌ {exc}"
        except httpx.HTTPStatusError as exc:
            return f"❌ HTTP {exc.response.status_code}"
        except httpx.RequestError as exc:
            return f"❌ 请求失败：{exc}"
        except Exception as exc:
            logger.exception("fetch_url failed")
            return f"❌ 下载失败：{exc}"

        if _is_texty(ctype):
            try:
                text = body.decode("utf-8", errors="replace")
            except Exception:
                return f"⚠️ 内容无法解码为 UTF-8（{len(body)} bytes, {ctype}）"
            preview = text if len(text) <= 8000 else text[:8000] + "\n...(已截断 8000 后)"
            return f"# URL: {url}\n# Content-Type: {ctype} ({len(body)} bytes)\n\n{preview}"

        # image → data URI，给主 LLM 自行判断（需要 vision 模型）
        if ctype.startswith("image/"):
            b64 = base64.b64encode(body).decode("ascii")
            data_uri = f"data:{ctype};base64,{b64}"
            return f"（图像 {len(body)} bytes, {ctype}）\n{data_uri}"

        # 其他二进制：告诉 Agent 不能直接读
        return (
            f"⚠️ URL {url} 的 Content-Type 是 {ctype}（{len(body)} bytes），"
            "非 text/image，暂不支持直接读取。如需处理，请让管理员补充专用工具"
            "（如 PDF/Office 解析）。"
        )

    return StructuredTool.from_function(
        coroutine=_fetch,
        name="fetch_url",
        description=(
            "下载 HTTP/HTTPS URL 指向的内容并返回文本（或图像 data URI）。"
            "用于读取用户上传到对象存储的附件，或外部 URL。"
            "参数：url(str，http://… 或 https://…)。"
            "限制：≤20MB；仅 text/* 和 application/json/yaml/xml/csv 等被直接解码；"
            "二进制除图像外不支持。"
        ),
    )
