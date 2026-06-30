"""Agent CRUD + Skill/MCP/AuxModel 绑定 + 单测端点。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.deps import AdminUser, DBSession
from app.models.agent import Agent
from app.schemas.agent import (
    AgentAuxModelBinding,
    AgentAuxModelBindingInput,
    AgentCreate,
    AgentDetail,
    AgentMCPBinding,
    AgentPublic,
    AgentSkillBinding,
    AgentTestRequest,
    AgentTestResponse,
    AgentUpdate,
    ModelInfo,
)
from app.services import agent_service
from app.skills_builtin import BuiltinToolContext

router = APIRouter(prefix="/api/agents", tags=["agents"])


async def _to_detail(db, agent: Agent) -> AgentDetail:
    model = await agent_service.get_agent_model(db, agent)
    model_info = ModelInfo.model_validate(model) if model else None
    return AgentDetail.model_validate(
        {
            **{c.name: getattr(agent, c.name) for c in agent.__table__.columns},
            "skill_bindings": [
                AgentSkillBinding(skill_id=b.skill_id, config=b.config) for b in agent.skills
            ],
            "mcp_bindings": [
                AgentMCPBinding(mcp_server_id=b.mcp_server_id, tool_filter=b.tool_filter)
                for b in agent.mcp_servers
            ],
            "aux_model_bindings": [
                AgentAuxModelBinding(
                    model_id=b.model_id,
                    role=b.role,  # type: ignore[arg-type]
                    alias=b.alias,
                    config=b.config,
                )
                for b in agent.aux_models
            ],
            "model": model_info,
        }
    )


@router.get("", response_model=list[AgentPublic])
async def list_agents(_: AdminUser, db: DBSession) -> list[AgentPublic]:
    items = await agent_service.list_agents(db)
    return [AgentPublic.model_validate(a) for a in items]


@router.post("", response_model=AgentDetail, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: AgentCreate, _: AdminUser, db: DBSession) -> AgentDetail:
    exists = await db.execute(select(Agent).where(Agent.name == payload.name))
    if exists.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="同名 Agent 已存在")
    try:
        agent = await agent_service.create_agent(db, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _to_detail(db, agent)


@router.get("/{agent_id}", response_model=AgentDetail)
async def get_agent(agent_id: uuid.UUID, _: AdminUser, db: DBSession) -> AgentDetail:
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在")
    return await _to_detail(db, agent)


@router.put("/{agent_id}", response_model=AgentDetail)
async def update_agent(
    agent_id: uuid.UUID, payload: AgentUpdate, _: AdminUser, db: DBSession
) -> AgentDetail:
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在")
    try:
        updated = await agent_service.update_agent(db, agent, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _to_detail(db, updated)


@router.get("/{agent_id}/cascade-preview")
async def cascade_preview(agent_id: uuid.UUID, _: AdminUser, db: DBSession) -> dict:
    """级联删 super 前的影响预览：会删哪些 Mission / 独占 worker，哪些 worker 因被其他
    super 使用（或系统对象）会保留。前端 confirm 弹窗据此给用户提示。"""
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在")
    from app.services import mission_service
    return await mission_service.preview_super_cascade(db, agent)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: uuid.UUID,
    _: AdminUser,
    db: DBSession,
    cascade: bool = Query(
        False,
        description=(
            "super 专用：true 时连带删除该 super 名下所有 Mission + super 本体（ADR-027 · worker "
            "是平台级共享资源，不级联删）。false（默认）时若 super 仍有运营实例则 409。"
        ),
    ),
) -> Response:
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在")
    # ADR-015 · 平台系统对象不可删除
    if getattr(agent, "is_system", False):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="平台系统对象（Builder Supervisor / builtin worker），不可删除",
        )
    # cascade + 该 agent 监管着 Mission（前端「super」= 任意监管 mission 的 agent，含 kind=builder
    # 的自动生成 supervisor）：连带删名下 Mission + 本体（ADR-027 · worker 平台级共享不级联删）。
    # 按「是否监管 mission」判断而非 kind，避免漏掉 kind!='super' 的 supervisor。
    if cascade:
        from app.models.mission import Mission as _M
        has_missions = (await db.execute(
            select(_M.id).where(_M.supervisor_agent_id == agent_id).limit(1)
        )).first() is not None
        if has_missions:
            from app.services import mission_service
            summary = await mission_service.delete_super_with_cascade(db, agent)
            return JSONResponse(status_code=status.HTTP_200_OK, content=summary)
    # ADR-027 · worker 是平台级共享资源（按 capability 全局发现，不再按 mission 预绑 mission_nodes），
    # 删除不再需要查节点引用。
    # super 删除前查运营实例：仍监管任一 Mission（missions.supervisor_agent_id，FK RESTRICT）
    # 则禁止——否则删带运营实例的 super 会裸抛 IntegrityError → 500。给可读 409。
    # 用 ORM 而非 raw SQL：UUID 列在 SQLite/Postgres 下存储格式不同，ORM 负责类型转换。
    from sqlalchemy import select as _select
    from app.models.mission import Mission as _Mission
    supervised = (await db.execute(
        _select(_Mission.name)
        .where(_Mission.supervisor_agent_id == agent_id)
        .order_by(_Mission.name).limit(10)
    )).scalars().all()
    if supervised:
        who = "、".join(supervised)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"该 super 仍有 {len(supervised)} 个运营实例（Mission）：{who}。请先删除这些 Mission 再删 super。",
        )
    await agent_service.delete_agent(db, agent)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Skill 绑定 ──
@router.post("/{agent_id}/skills/{skill_id}", response_model=AgentSkillBinding)
async def add_skill(
    agent_id: uuid.UUID,
    skill_id: uuid.UUID,
    _: AdminUser,
    db: DBSession,
    config: dict | None = None,
) -> AgentSkillBinding:
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在")
    try:
        binding = await agent_service.add_skill(db, agent_id, skill_id, config)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AgentSkillBinding(skill_id=binding.skill_id, config=binding.config)


@router.delete("/{agent_id}/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_skill(
    agent_id: uuid.UUID, skill_id: uuid.UUID, _: AdminUser, db: DBSession
) -> None:
    ok = await agent_service.remove_skill(db, agent_id, skill_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="绑定不存在")


# ── MCP 绑定 ──
@router.post("/{agent_id}/mcp-servers/{mcp_id}", response_model=AgentMCPBinding)
async def add_mcp(
    agent_id: uuid.UUID,
    mcp_id: uuid.UUID,
    _: AdminUser,
    db: DBSession,
    tool_filter: list[str] | None = None,
) -> AgentMCPBinding:
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在")
    binding = await agent_service.add_mcp(db, agent_id, mcp_id, tool_filter)
    return AgentMCPBinding(mcp_server_id=binding.mcp_server_id, tool_filter=binding.tool_filter)


@router.delete("/{agent_id}/mcp-servers/{mcp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_mcp(agent_id: uuid.UUID, mcp_id: uuid.UUID, _: AdminUser, db: DBSession) -> None:
    ok = await agent_service.remove_mcp(db, agent_id, mcp_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="绑定不存在")


# ── Aux Model 绑定 ──
@router.post("/{agent_id}/aux-models/{model_id}", response_model=AgentAuxModelBinding)
async def add_aux_model(
    agent_id: uuid.UUID,
    model_id: uuid.UUID,
    payload: AgentAuxModelBindingInput,
    _: AdminUser,
    db: DBSession,
) -> AgentAuxModelBinding:
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在")
    try:
        binding = await agent_service.add_aux_model(
            db,
            agent_id,
            model_id,
            role=payload.role,
            alias=payload.alias,
            config=payload.config,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AgentAuxModelBinding(
        model_id=binding.model_id,
        role=binding.role,  # type: ignore[arg-type]
        alias=binding.alias,
        config=binding.config,
    )


@router.delete("/{agent_id}/aux-models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_aux_model(
    agent_id: uuid.UUID, model_id: uuid.UUID, _: AdminUser, db: DBSession
) -> None:
    ok = await agent_service.remove_aux_model(db, agent_id, model_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="绑定不存在")


# ── 单测（dry-run）──
@router.post("/{agent_id}/test", response_model=AgentTestResponse)
async def test_agent(
    agent_id: uuid.UUID,
    payload: AgentTestRequest,
    _: AdminUser,
    db: DBSession,
) -> AgentTestResponse:
    """Agent 单轮 dry-run 测试：真实调用 LLM，不绑 tools（避免副作用）。

    返回：
    - ok：调用成功与否
    - output：模型真实返回文本（system prompt + 用户输入 → LLM）
    - tools_loaded：绑定的 builtin 工具数量（仅供参考，本次调用未实际绑定）
    - error：失败原因
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.models.provider import LLMModel

    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在")
    try:
        ctx = BuiltinToolContext()
        tools = agent_service.load_builtin_tools(agent, ctx)
        prompt = agent_service.assemble_system_prompt(agent)
        model = await db.get(LLMModel, agent.model_id)
        if not model:
            return AgentTestResponse(
                ok=False, error="Agent 主模型不存在（llm_models.id 指向失效）", tools_loaded=len(tools)
            )
        # 构造真实 LLM 并走 streaming（与生产链路一致 —— 避免 ainvoke 下游对 stream=True
        # 的 kwargs 混淆；同时 TTFT 更快，dry-run 体验更好）
        llm = await agent_service._build_llm(db, model, agent)
        parts: list[str] = []
        async for chunk in llm._astream(  # type: ignore[attr-defined]
            [SystemMessage(content=prompt), HumanMessage(content=payload.input)]
        ):
            c = chunk.message.content
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                for block in c:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
        text = "".join(parts).strip()
        if not text:
            text = "（模型未返回文本，可能全部是工具调用或 thinking）"
        return AgentTestResponse(ok=True, output=text, tools_loaded=len(tools))
    except Exception as exc:  # pragma: no cover
        return AgentTestResponse(ok=False, error=f"{type(exc).__name__}: {exc}")
