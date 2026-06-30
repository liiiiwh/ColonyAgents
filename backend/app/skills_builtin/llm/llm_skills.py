"""LLM 资源查询工具：list_providers / list_models / resolve_model_id

Builder Worker 需要拿到合法的 LLMModel UUID 才能 agent_create；之前没有
查询工具导致 Worker 瞎试 model_id 失败 4 次的死循环。

resolve_model_id 同时支持 `provider/model_id` 字符串解析（如
`nebula/claude-opus-4-6`），让 agent_create 容错性更好。
"""

from __future__ import annotations

import logging
import uuid

from langchain_core.tools import StructuredTool
from sqlalchemy import select

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


def list_providers_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _run(enabled_only: bool = True) -> dict:
        """列出所有已配置的 LLM Provider。返回 `{items: [{id, name, provider_type, is_enabled}]}`。"""
        from app.models.provider import LLMProvider

        if ctx.db_factory is None:
            return {"ok": False, "error": "db_factory not available"}
        async with ctx.db_factory() as db:
            stmt = select(LLMProvider)
            if enabled_only:
                stmt = stmt.where(LLMProvider.is_enabled.is_(True))
            rows = (await db.execute(stmt.order_by(LLMProvider.name))).scalars().all()
            return {
                "ok": True,
                "items": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "provider_type": p.provider_type,
                        "is_enabled": p.is_enabled,
                    }
                    for p in rows
                ],
            }

    return StructuredTool.from_function(
        coroutine=_run,
        name="list_providers",
        description=(
            "列出已配置的 LLM Provider（如 nebula / e2e-gemini / openai 等）。"
            "用于 list_models 的可选 provider 过滤。"
        ),
    )


def list_models_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _run(
        provider_name: str = "",
        model_type: str = "chat",
        enabled_only: bool = True,
        limit: int = 50,
    ) -> dict:
        """列出可用 LLM 模型。**Builder Worker 在 agent_create 之前必调**。

        Args:
            provider_name: 仅返回该 provider 的模型（如 'nebula' / 'e2e-gemini'）；空表示全部
            model_type: 'chat' / 'embedding' / 'completion'，默认 chat
            enabled_only: 是否仅列已启用的
            limit: 返回条数上限（默认 50）

        Returns:
            `{items: [{id: UUID, model_id, provider_name, display_name, supports_vision,
                       supports_function_calling, context_window}]}`
            **`id` 是 UUID 字符串，用作 agent_create(model_id=...) 的入参。**
        """
        from app.models.provider import LLMModel, LLMProvider

        if ctx.db_factory is None:
            return {"ok": False, "error": "db_factory not available"}
        limit = max(1, min(int(limit) if isinstance(limit, int) else 50, 200))
        async with ctx.db_factory() as db:
            stmt = (
                select(LLMModel, LLMProvider)
                .join(LLMProvider, LLMProvider.id == LLMModel.provider_id)
                .where(LLMModel.model_type == model_type)
            )
            if enabled_only:
                stmt = stmt.where(
                    LLMModel.is_enabled.is_(True), LLMProvider.is_enabled.is_(True)
                )
            if provider_name:
                stmt = stmt.where(LLMProvider.name == provider_name)
            stmt = stmt.order_by(LLMProvider.name, LLMModel.model_id).limit(limit)
            rows = (await db.execute(stmt)).all()
            return {
                "ok": True,
                "total": len(rows),
                "items": [
                    {
                        "id": str(m.id),  # agent_create 用这个
                        "model_id": m.model_id,  # provider 侧的名字（如 claude-opus-4-6）
                        "provider_name": p.name,
                        "display_name": m.display_name,
                        "supports_vision": m.supports_vision,
                        "supports_function_calling": m.supports_function_calling,
                        "context_window": m.context_window,
                    }
                    for m, p in rows
                ],
                "hint": (
                    "把 items[i].id（UUID）作为 agent_create(model_id=...) 的入参。"
                    "agent_create 也接受 'provider_name/model_id' 字符串（如 'nebula/claude-opus-4-6'）。"
                ),
            }

    return StructuredTool.from_function(
        coroutine=_run,
        name="list_models",
        description=(
            "列出可用 LLM 模型。返回项目里每条 model 的 UUID（用作 agent_create 的 model_id 参数）。"
            "Builder Worker 在 agent_create 前**必须**先调一次，否则 model_id 无法确定。"
        ),
    )


async def resolve_model_id(db, spec: str) -> uuid.UUID | None:
    """解析 model_id 入参：
    - UUID 字符串 → 直接转 UUID
    - 'provider_name/model_id'（如 'nebula/claude-opus-4-6'）→ 查 LLMModel.id
    - 裸 model_id（如 'claude-opus-4-6'）→ 查；若跨 provider 重名返回 None

    返回 LLMModel UUID 或 None（未找到 / 歧义）。
    """
    if not spec:
        return None
    spec = spec.strip()
    # 1) UUID 路径
    try:
        return uuid.UUID(spec)
    except (ValueError, AttributeError):
        pass

    from app.models.provider import LLMModel, LLMProvider

    # 2) provider/model_id
    if "/" in spec:
        provider_name, model_id = spec.split("/", 1)
        row = (
            await db.execute(
                select(LLMModel)
                .join(LLMProvider, LLMProvider.id == LLMModel.provider_id)
                .where(LLMProvider.name == provider_name, LLMModel.model_id == model_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        return row.id if row else None

    # 3) 裸 model_id
    rows = (
        await db.execute(select(LLMModel).where(LLMModel.model_id == spec))
    ).scalars().all()
    if len(rows) == 1:
        return rows[0].id
    return None  # 0 或多个 → 歧义
