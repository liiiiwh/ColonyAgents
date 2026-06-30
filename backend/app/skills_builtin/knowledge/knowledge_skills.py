"""知识库工具族：向量检索 / 索引。

设计（v2 · per-project KB）：
- 每个 Mission 自动持有一条 KB（slug='kb-{project.slug}'）
- skills 在 builder/worker 里调用时**默认走 ctx.mission_id 对应的 KB**
- 显式传 `kb_id` 时定向查询；省略 `kb_id` 且无 ctx.mission_id 时降级遍历所有 KB
- `knowledge_search` 支持 `min_score` 过滤；返回内容 + score，输出格式适合 LLM 阅读
"""

from __future__ import annotations

import logging
import uuid

from langchain_core.tools import StructuredTool

from app.services import knowledge_service
from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


def _parse_uuid(val: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(val)
    except (ValueError, TypeError):
        return None


async def _resolve_target_kb(
    ctx: BuiltinToolContext, kb_id: str | None, db
):
    """决定 search/index 该走哪个 KB。

    优先级：
    1) 显式传入的 kb_id（UUID）
    2) ctx.mission_id 对应的项目 KB
    3) 返回 None，让调用方决定是降级遍历还是报错
    """
    if kb_id:
        kb_uuid = _parse_uuid(kb_id)
        if not kb_uuid:
            return None, f"kb_id 非法：{kb_id}"
        kb = await knowledge_service.get_kb(db, kb_uuid)
        if not kb:
            return None, f"知识库 {kb_id} 不存在"
        return kb, None
    if ctx.mission_id:
        kb = await knowledge_service.get_kb_by_project(db, ctx.mission_id)
        if kb:
            return kb, None
    return None, None  # 让上层决定


def knowledge_search_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _search(
        query: str,
        kb_id: str | None = None,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> str:
        """
        v6.C · 3-tier 语义检索（mission → platform 自动 union；项目优先）。
        - **强烈建议省略 `kb_id`** —— 自动 union 当前 mission KB + platform 共享 KB
        - 显式传 `kb_id`（UUID）= 单一定向（admin 共享 KB / 其他项目 KB）
        - `min_score` 过滤低分噪声（典型阈值 0.5）
        """
        if ctx.db_factory is None:
            return "❌ 工具上下文缺失（db_factory）"
        top_k = min(max(top_k, 1), 20)
        min_score = max(0.0, min(1.0, float(min_score)))

        async with ctx.db_factory() as db:
            kb, err = await _resolve_target_kb(ctx, kb_id, db)
            if err:
                return f"❌ {err}"

            if kb is not None:
                # v6.C · 3-tier union：mission/project KB + platform KB
                mission_hits = await knowledge_service.search(db, kb, query, top_k=top_k)
                mission_hits = [
                    {**h, "_tier": "mission", "kb_name": kb.name}
                    for h in mission_hits if h.get("score", 0) >= min_score
                ]
                platform_hits: list[dict] = []
                if kb_id is None:  # 自动模式才 union platform
                    try:
                        pkb = await knowledge_service.get_platform_kb(db)
                        if pkb is not None and pkb.id != kb.id:
                            raw = await knowledge_service.search(db, pkb, query, top_k=top_k)
                            platform_hits = [
                                {**h, "_tier": "platform", "kb_name": pkb.name}
                                for h in raw if h.get("score", 0) >= min_score
                            ]
                    except Exception:
                        logger.exception("platform KB union failed; mission-only fallback")
                # union + 项目优先（同 score mission 排前）
                merged = mission_hits + platform_hits
                merged.sort(key=lambda x: (x.get("score", 0), 1 if x["_tier"] == "mission" else 0), reverse=True)
                merged = merged[:top_k]
                title = f"{kb.name} + platform-shared (3-tier union)" if platform_hits else kb.name
                return _format_hits(title, merged, show_source=bool(platform_hits))

            # 既无 kb_id 也无 ctx.mission_id KB —— 兜底遍历所有 KB
            kbs = await knowledge_service.list_kbs(db)
            if not kbs:
                return "⚠️ 系统内尚无任何知识库；创建项目时会自动建专属 KB。"
            pooled: list[dict] = []
            for k in kbs:
                try:
                    hits = await knowledge_service.search(db, k, query, top_k=top_k)
                except Exception:
                    logger.exception("kb=%s 检索失败，跳过", k.name)
                    continue
                for h in hits:
                    if h.get("score", 0) >= min_score:
                        pooled.append({**h, "kb_name": k.name, "kb_id": str(k.id)})
        if not pooled:
            return (
                f"⚠️ {len(kbs)} 个 KB 均未命中 score≥{min_score:.2f} 的片段。"
                "可能 KB 还没被填充；用 `knowledge_index` 写入相关知识。"
            )
        pooled.sort(key=lambda x: x.get("score", 0), reverse=True)
        pooled = pooled[:top_k]
        return _format_hits("全部 KB（自动遍历，无项目 KB 时兜底）", pooled, show_source=True)

    return StructuredTool.from_function(
        coroutine=_search,
        name="knowledge_search",
        description=(
            "在知识库做向量语义检索；返回片段内容 + score（0~1，越高越相关）。\n"
            "**默认不传 kb_id** = 查当前项目专属 KB（自动）。\n"
            "参数：query(str 必填) / kb_id(str 可选，UUID，跨项目查时用) / "
            "top_k(int 默认 5，最大 20) / min_score(float 默认 0.0；推荐 ≥ 0.5 过噪声)。"
        ),
    )


def _format_hits(kb_name: str, hits: list[dict], show_source: bool = False) -> str:
    if not hits:
        return f"⚠️ {kb_name} 未命中任何片段"
    lines = [f"# {kb_name} 检索结果（Top {len(hits)}）", ""]
    for i, h in enumerate(hits, 1):
        content = h["content"]
        preview = content if len(content) <= 600 else content[:600] + "..."
        src = f" [from {h.get('kb_name')}]" if show_source and h.get("kb_name") else ""
        lines.append(f"## {i}. score={h.get('score', 0):.4f}{src}")
        lines.append(preview)
        lines.append("")
    return "\n".join(lines)


def list_knowledge_bases_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _list() -> str:
        if ctx.db_factory is None:
            return "❌ 工具上下文缺失"
        async with ctx.db_factory() as db:
            kbs = await knowledge_service.list_kbs(db)
        if not kbs:
            return "（系统内尚无知识库）"
        lines = ["# 可用知识库列表"]
        my_pid = ctx.mission_id
        for kb in kbs:
            mine = "（当前项目自动）" if my_pid and kb.mission_id == my_pid else ""
            scope = (
                "project" if kb.mission_id else ("shared" if not kb.mission_id else "")
            )
            tags = ",".join(kb.tags or []) if hasattr(kb, "tags") and kb.tags else ""
            extra = f" tags=[{tags}]" if tags else ""
            lines.append(
                f"- **{kb.name}**{mine} (id=`{kb.id}` scope={scope}{extra}) — "
                f"{kb.description or '无描述'}"
            )
        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_list,
        name="list_knowledge_bases",
        description=(
            "列出系统内所有可用知识库（标注当前项目 KB / 跨项目共享 KB）。"
            "通常你不需要调它 —— knowledge_search 默认就走当前项目 KB。"
            "想跨项目检索时才用它发现可用 KB。"
        ),
    )


def knowledge_index_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _index(filename: str, content: str, kb_id: str | None = None) -> str:
        """**默认不传 kb_id** = 写入当前项目专属 KB。"""
        if ctx.db_factory is None:
            return "❌ 工具上下文缺失"
        if not content.strip():
            return "❌ content 不能为空"
        async with ctx.db_factory() as db:
            kb, err = await _resolve_target_kb(ctx, kb_id, db)
            if err:
                return f"❌ {err}"
            if kb is None:
                return (
                    "❌ 找不到目标 KB：当前 ctx 没有 mission_id 且未显式指定 kb_id。"
                    "调用方应传 kb_id，或确保该 Agent 运行在某个 Mission 上下文里。"
                )
            doc = await knowledge_service.index_document(db, kb, filename, content)
        logger.info(
            "📚 knowledge_index: kb=%s doc=%s chunks=%d",
            kb.name, filename, doc.chunk_count,
        )
        return f"✅ 已索引 {filename} 到 {kb.name}（{doc.chunk_count} 个 chunks）"

    return StructuredTool.from_function(
        coroutine=_index,
        name="knowledge_index",
        description=(
            "把文本作为文档索引到知识库（自动分块 + embedding + 入库）。"
            "**默认写入当前项目专属 KB**（自动）；显式传 kb_id 写到其他 KB。"
            "参数：filename(str) / content(str) / kb_id(str 可选 UUID)。"
            "⚠️ 写入是结构性操作；像写产物总结那样调用，**不要**用它当 memory_append 用。"
        ),
    )
