"""v6 · promote_to_platform & platform_knowledge_search.

Super / Builder 都可调 promote_to_platform 把一条经验从 project KB 推到 platform KB。
所有 super 的 knowledge_search 默认会同时查 platform + project（项目优先）。
"""
from __future__ import annotations

import json
import logging
import uuid

from langchain_core.tools import StructuredTool

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


def promote_to_platform_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _promote(filename: str, content: str, reason: str = "") -> str:
        """v6 · 把一段经验 / 规则 / 风控发现推到平台共享 KB；其它 super 即可 search。

        参数：
        - filename: 简短标识（如 "xhs_rate_limit_2026q2"）
        - content: markdown / 文本内容
        - reason: 为什么 promote（审计用）
        """
        from app.services import knowledge_service
        if ctx.db_factory is None:
            return json.dumps({"ok": False, "error": "缺 db_factory"})
        async with ctx.db_factory() as db:
            kb = await knowledge_service.get_platform_kb(db)
            if kb is None:
                return json.dumps({"ok": False, "error": "platform KB 未初始化（请先启动后端 seed）"})
            try:
                doc = await knowledge_service.index_document(
                    db, kb, filename=filename or "promotion.md",
                    content=content,
                )
                return json.dumps({
                    "ok": True,
                    "document_id": str(doc.id),
                    "kb": "platform-shared",
                    "reason": reason,
                }, ensure_ascii=False)
            except Exception as e:
                logger.exception("[promote_to_platform] failed")
                return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    return StructuredTool.from_function(
        coroutine=_promote,
        name="promote_to_platform",
        description=(
            "v6 · 把一条经验/规则推到平台共享 KB，让所有其它 super 都能 search 到。"
            "适用：worker 运行期发现 rate limit / 风控规则 / 跨平台通用应对；"
            "Builder 设计成功 super 的复用模板。"
            "参数 filename(str)+content(str)+reason(str)。"
        ),
    )


def platform_knowledge_search_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _search(query: str, top_k: int = 5) -> str:
        """v6 · 仅查 platform shared KB（跟 knowledge_search 区别：那个查本项目）。"""
        from app.services import knowledge_service
        if ctx.db_factory is None:
            return json.dumps({"ok": False, "error": "缺 db_factory"})
        async with ctx.db_factory() as db:
            kb = await knowledge_service.get_platform_kb(db)
            if kb is None:
                return json.dumps({"ok": True, "results": [], "note": "platform KB 未初始化"})
            try:
                hits = await knowledge_service.search(db, kb, query=query, top_k=top_k)
                return json.dumps({"ok": True, "results": hits}, ensure_ascii=False)
            except Exception as e:
                logger.exception("[platform_knowledge_search] failed")
                return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    return StructuredTool.from_function(
        coroutine=_search,
        name="platform_knowledge_search",
        description=(
            "v6 · 仅查平台共享 KB（跨 project 经验复用）。"
            "knowledge_search 已默认含项目 KB；想跨 project 找历史经验来这里。"
            "参数 query(str)+top_k(int=5)。"
        ),
    )
