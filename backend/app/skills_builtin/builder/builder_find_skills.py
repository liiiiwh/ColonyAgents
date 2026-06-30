"""v6 · Builder-only find_workers skill.

list_workers (super-dispatch) 只能按 capability slug 查；
Builder 在设计 super 时需要按 (action / side_effects / approval) 复合查询 ——
本 skill 接 capability_index.find_workers。
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import StructuredTool

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


def find_workers_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _find(
        action: str = "",
        capability: str = "",
        requires_approval: bool | None = None,
        parallel_safe: bool | None = None,
        exclude_side_effects: list[str] | None = None,
        limit: int = 30,
    ) -> str:
        """v6 · 复合查询平台 worker catalog。

        参数：
        - action: 要找的 action 名（如 'publish_note'）
        - capability: capability slug 过滤
        - requires_approval: True / False / None=不限
        - parallel_safe: True / False / None=不限
        - exclude_side_effects: 想排除的 side_effects tag list（如 ['external_write']）
        - limit: 上限

        返回 list of {worker_agent_id, worker_name, capability, action, requires_approval,
                      parallel_safe, side_effects, concurrency_hint, rate_limit}
        """
        from app.domain.builder.capability_index import find_workers

        if ctx.db_factory is None:
            return json.dumps({"ok": False, "error": "缺 db_factory"})
        async with ctx.db_factory() as db:
            try:
                rows = await find_workers(
                    db,
                    action=action or None,
                    capability=capability or None,
                    requires_approval=requires_approval,
                    parallel_safe=parallel_safe,
                    exclude_side_effects=exclude_side_effects or None,
                    limit=limit,
                )
            except Exception as e:
                logger.exception("[find_workers] failed")
                return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
        return json.dumps({"ok": True, "count": len(rows), "items": rows}, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_find,
        name="find_workers",
        description=(
            "（Builder-only v6）按 action / side_effects / approval / parallel 等复合维度查 worker catalog。"
            "比 list_workers (按 capability slug 查) 强：可问『谁支持 publish_note 但不要 external_write 的』。"
            "在设计 super / 评估能力空缺时优先调它。"
        ),
    )
