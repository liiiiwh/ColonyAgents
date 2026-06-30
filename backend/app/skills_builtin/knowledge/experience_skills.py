"""经验学习闭环 - Builder Supervisor 专用。

`experience_record` 是带「**强制 approval**」语义包装的 knowledge_index：
- 写入位置：默认当前项目专属 KB（Builder Mission 的 `kb-builder` —— 跨 Mission 经验沉淀地）
- 写入门禁：必须 `confirmed=True`；首次调用强制返回提示让 Supervisor 先调
  `request_approval` 拿到用户同意后才能再次以 confirmed=True 调用
- 内容格式：约束成 Markdown 模板（场景 / 用到的 skill / 踩坑 / 复用提示），避免 Supervisor
  乱写或把日常 chitchat 也归档

Builder Supervisor 协议会在合适时刻（项目落地完成、用户表扬、踩坑修复后）主动提议归档。
"""

from __future__ import annotations

import logging

from langchain_core.tools import StructuredTool

from app.services import knowledge_service
from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


_TEMPLATE_HINT = (
    "# {title}\n\n"
    "**场景 / 用户需求**\n{scenario}\n\n"
    "**采用的方案**\n{solution}\n\n"
    "**关键 skill / agent 编排**\n{skills_agents}\n\n"
    "**踩过的坑 + 解决方式**\n{pitfalls}\n\n"
    "**复用提示（下次类似需求怎么走捷径）**\n{reuse_hint}"
)


def experience_record_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _run(
        title: str,
        scenario: str,
        solution: str,
        skills_agents: str,
        pitfalls: str,
        reuse_hint: str,
        confirmed: bool = False,
    ) -> dict:
        """把一次项目经验归档到当前项目 KB（默认就是 Builder Mission 的 kb-builder）。

        ⚠️ 危险动作：经验会被未来所有项目的 knowledge_search 召回，所以**必须**先调
        `request_approval` 拿到用户对完整内容的同意，再以 `confirmed=True` 重新调用。
        """
        if ctx.db_factory is None:
            return {"ok": False, "error": "工具上下文缺失（db_factory）"}
        if ctx.mission_id is None:
            return {
                "ok": False,
                "error": (
                    "经验只能在 Mission 上下文里归档（自动写入该项目的 KB）。"
                    "通常 Builder Supervisor 调它时已在 Builder Mission 内。"
                ),
            }
        for k, v in [
            ("title", title), ("scenario", scenario), ("solution", solution),
            ("skills_agents", skills_agents), ("reuse_hint", reuse_hint),
        ]:
            if not (v and v.strip()):
                return {"ok": False, "error": f"必填字段 {k} 不能为空"}

        # 强制 approval：首次调用一律拒绝
        if not confirmed:
            preview = _TEMPLATE_HINT.format(
                title=title.strip(),
                scenario=scenario.strip(),
                solution=solution.strip(),
                skills_agents=skills_agents.strip(),
                pitfalls=(pitfalls or "（无）").strip(),
                reuse_hint=reuse_hint.strip(),
            )
            return {
                "ok": False,
                "error": "EXPERIENCE_NEEDS_APPROVAL",
                "instruction": (
                    "经验归档是写入跨项目复用的知识；必须先调 `request_approval` 把"
                    "下面这段完整内容给用户确认，用户同意后以 confirmed=True 重新调用。"
                ),
                "preview_markdown": preview,
            }

        # 真写入
        content = _TEMPLATE_HINT.format(
            title=title.strip(),
            scenario=scenario.strip(),
            solution=solution.strip(),
            skills_agents=skills_agents.strip(),
            pitfalls=(pitfalls or "（无）").strip(),
            reuse_hint=reuse_hint.strip(),
        )
        async with ctx.db_factory() as db:
            kb = await knowledge_service.get_kb_by_project(db, ctx.mission_id)
            if kb is None:
                return {
                    "ok": False,
                    "error": (
                        f"当前 mission_id={ctx.mission_id} 没有专属 KB。"
                        "新建 project 时会自动建；老项目需要先调一次后端 backfill。"
                    ),
                }
            # 文件名加时间戳防覆盖
            from datetime import datetime, timezone
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safe_title = "".join(c if c.isalnum() or c in "-_." else "_" for c in title)[:60]
            filename = f"experience-{ts}-{safe_title}.md"
            doc = await knowledge_service.index_document(db, kb, filename, content)
        logger.info(
            "[experience_record] kb=%s doc=%s chunks=%d", kb.name, filename, doc.chunk_count
        )
        return {
            "ok": True,
            "kb_name": kb.name,
            "kb_id": str(kb.id),
            "document_id": str(doc.id),
            "filename": filename,
            "chunk_count": doc.chunk_count,
            "preview_content": content[:400],
        }

    return StructuredTool.from_function(
        coroutine=_run,
        name="experience_record",
        description=(
            "（Builder Supervisor 专用）把一次项目经验归档到 KB，供未来 knowledge_search 召回。\n"
            "**必须先 request_approval 拿到用户同意完整内容**，再以 confirmed=True 重新调用。\n"
            "参数：title / scenario / solution / skills_agents / pitfalls / reuse_hint / "
            "confirmed(bool 必须为 True 才真写)。"
        ),
    )
