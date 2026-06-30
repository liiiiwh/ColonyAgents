"""E2E probe: image aux-model 绑定闭环（对真实 DB + 真实 image key）。

证明 BUG#2 修复后整条回路闭合：
  build_worker(aux_models=[image]) → apply_worker_spec 落 AgentAuxModel
  → 运行时 _resolve_binding(role='image') 找得到并解出真实 provider/key
  → 实际调一次图像生成，确认出图（之前「建得出架子却出不了图」）。

跑完删除临时 worker（cascade 删绑定），不留污染。容器内执行：
  docker exec colony-backend python /app/scripts/e2e_image_binding_probe.py
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

CAP = "e2e_img_probe"


async def main() -> None:
    # 先把所有 model 模块导进来，填满 SQLAlchemy mapper registry（否则关系名解析不到）。
    import app.models.user  # noqa
    import app.models.provider  # noqa
    import app.models.agent  # noqa
    import app.models.skill  # noqa
    import app.models.mission  # noqa
    import app.models.knowledge  # noqa

    from app.db.session import AsyncSessionLocal as async_session_factory
    from app.models.provider import LLMModel
    from app.models.agent import Agent, AgentAuxModel
    from app.domain.builder import WorkerSpec
    from app.domain.builder.factory import apply_worker_spec

    out: list[str] = []

    # 1) 真实 DB 里挑一个启用的 image 模型 + 一个 chat 模型（worker 主模型）
    async with async_session_factory() as db:
        img = (await db.execute(
            select(LLMModel).where(LLMModel.model_type == "image", LLMModel.is_enabled == True)  # noqa: E712
        )).scalars().first()
        chat = (await db.execute(
            select(LLMModel).where(LLMModel.model_type == "chat", LLMModel.is_enabled == True)  # noqa: E712
        )).scalars().first()
    assert img is not None, "DB 里没有启用的 image 模型"
    assert chat is not None, "DB 里没有启用的 chat 模型"
    out.append(f"[seed] image_model={img.model_id} uuid={img.id}; chat_model={chat.model_id}")

    # 2) 清掉可能的上轮残留
    async with async_session_factory() as db:
        old = (await db.execute(select(Agent).where(Agent.kind == "worker", Agent.capability == CAP))).scalars().all()
        for a in old:
            await db.delete(a)
        await db.commit()

    # 3) build_worker 等价：apply_worker_spec(aux_models=[image]) —— 这是被修的路径
    spec = WorkerSpec(
        name="e2e image probe", slug="e2e_img_probe", model_id=chat.id,
        capability=CAP,
        capability_contract={
            "capability": CAP, "version": "1.0.0",
            "advertises": [{"action": "render", "side_effects": [], "requires_approval": False}],
        },
        aux_models=[{"role": "image", "model_id": str(img.id), "alias": "banana"}],
    )
    async with async_session_factory() as db:
        ref = await apply_worker_spec(db, spec, created_by=None)
    out.append(f"[apply] worker_agent_id={ref.agent_id}")

    # 4) 断言绑定真落库
    async with async_session_factory() as db:
        rows = (await db.execute(
            select(AgentAuxModel).where(AgentAuxModel.agent_id == ref.agent_id)
        )).scalars().all()
    assert len(rows) == 1 and rows[0].role == "image" and rows[0].model_id == img.id, \
        f"绑定未落库: {rows}"
    out.append(f"[persist] AgentAuxModel OK role={rows[0].role} alias={rows[0].alias}")

    # 5) 运行时读路径：_resolve_binding 找得到并解出真实 provider/key
    from app.skills_builtin.context import BuiltinToolContext
    from app.skills_builtin.llm.aux_model_skills import _resolve_binding
    ctx = BuiltinToolContext(db_factory=async_session_factory, extra={"agent_id": ref.agent_id})
    binding, err = await _resolve_binding(ctx, "image")
    assert binding is not None, f"_resolve_binding 失败: {err}"
    assert binding["model_type"] == "image", binding
    out.append(f"[resolve] provider={binding['provider_type']} model={binding['model_id']} "
               f"key_len={len(binding['api_key'] or '')} base_url={binding.get('base_url')}")

    # 6) 真的调图像生成（外部 API）。逐个试所有启用的 image 模型，看哪个真能出图。
    #    通过直接改这个临时 worker 的 image 绑定到不同模型来复用同一条解析路径。
    from app.skills_builtin.llm.aux_model_skills import invoke_aux_model_tool
    async with async_session_factory() as db:
        all_imgs = (await db.execute(
            select(LLMModel).where(LLMModel.model_type == "image", LLMModel.is_enabled == True)  # noqa: E712
        )).scalars().all()
        all_imgs = [(m.id, m.model_id) for m in all_imgs]
    for mid, mname in all_imgs:
        async with async_session_factory() as db:
            b = await db.get(AgentAuxModel, (ref.agent_id, rows[0].model_id))
            # 重绑该 worker 的 image 角色到当前模型
            await db.delete(b) if b else None
            await db.commit()
        async with async_session_factory() as db:
            db.add(AgentAuxModel(agent_id=ref.agent_id, model_id=mid, role="image", alias="banana", config={}))
            await db.commit()
        rows = [type("R", (), {"model_id": mid})()]  # 让下轮 delete 找到当前绑定
        tool = invoke_aux_model_tool(ctx)
        try:
            res = await tool.coroutine(
                alias_or_role="image",
                input="a tiny red circle on a white background, minimal flat icon",
            )
            text = str(res)
            ok = ("http" in text and "404" not in text and "失败" not in text)
            out.append(f"[generate] {mname}: {'✅ IMAGE' if ok else '✗'} → {text[:180]}")
        except Exception as exc:  # noqa: BLE001
            out.append(f"[generate] {mname}: ERROR {type(exc).__name__}: {str(exc)[:160]}")

    # 7) 清理临时 worker（cascade 删绑定）
    async with async_session_factory() as db:
        a = await db.get(Agent, ref.agent_id)
        if a is not None:
            await db.delete(a)
            await db.commit()
    out.append("[cleanup] temp worker deleted")

    print("\n".join(out))


if __name__ == "__main__":
    asyncio.run(main())
