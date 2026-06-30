"""微信审批人发来消息后的意图分类 + 上下文构建。

代替原来「严格 <id> <选项>」格式匹配，改成 LLM-judged 自然语言：
- 「ok 发吧」「行」「同意」→ decide pending（如果该审批人只有 1 条 pending 就用它；多条则反问）
- 「不行」「驳回」→ decide reject
- 「现在在干嘛」「进度」「状态」→ 拉对应 daemon 的 supervisor memory + workspace 给个总结
- 「停一下」「暂停」「重启」→ ⚠️ 高风险动作，不直接执行，回复让用户确认后再做（后续可加 lifecycle_control，目前先只查不动）
- 模糊/含混 → 提示 + 给候选

输入：from_user_id, text, account
输出：{
    intent: 'decide_approval' | 'query_status' | 'unclear',
    target_pending_id?: <request_id>,    # decide 时
    option?: <选项文本>,                  # decide 时
    target_project_slug?: <slug>,        # query 时
    reply_text: <要回给用户的内容>,
}

调用方（poller）按 intent 做事 + 把 reply_text 发回用户。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approvals import (
    PendingApproval,
    MissionApprovalChannel,
    WechatClawbotAccount,
)
from app.models.mission import Mission, MissionAgentMemory

logger = logging.getLogger(__name__)


async def list_reviewer_projects(
    db: AsyncSession, account: WechatClawbotAccount, wechat_user_id: str
) -> list[Mission]:
    """该用户作为 reviewer 挂在哪些 project 上。"""
    rows = (
        await db.execute(
            select(MissionApprovalChannel).where(
                MissionApprovalChannel.clawbot_account_id == account.id
            )
        )
    ).scalars().all()
    is_global_reviewer = wechat_user_id in (account.reviewers or [])
    project_ids: list = []
    for r in rows:
        # 项目级 reviewer 列表覆盖；空则继承 account.reviewers
        plist = list(r.reviewer_wechat_ids or [])
        if wechat_user_id in plist or (not plist and is_global_reviewer):
            project_ids.append(r.mission_id)
    if not project_ids:
        return []
    projects = (
        await db.execute(select(Mission).where(Mission.id.in_(project_ids)))
    ).scalars().all()
    return list(projects)


async def list_pending_for_reviewer(
    db: AsyncSession, projects: list[Mission]
) -> list[PendingApproval]:
    """这些项目里所有 pending 状态的审批。"""
    if not projects:
        return []
    pids = [p.id for p in projects]
    rows = (
        await db.execute(
            select(PendingApproval)
            .where(PendingApproval.mission_id.in_(pids))
            .where(PendingApproval.status == "pending")
            .order_by(PendingApproval.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


async def _project_summary(db: AsyncSession, project: Mission) -> str:
    """拉项目当前状态摘要：runtime + 最近 supervisor memory 末尾。"""
    from app.models.mission import MissionRunState

    rs = (
        await db.execute(
            select(MissionRunState).where(MissionRunState.mission_id == project.id)
        )
    ).scalar_one_or_none()
    sup_mem = (
        await db.execute(
            select(MissionAgentMemory).where(
                MissionAgentMemory.mission_id == project.id,
                MissionAgentMemory.agent_node_name == "supervisor",
            )
        )
    ).scalar_one_or_none()
    runtime = "未启动 daemon" if rs is None else (
        f"daemon {rs.status} / run_count={rs.run_count}"
        + (f" / 心跳 {rs.last_heartbeat_at.isoformat()}" if rs.last_heartbeat_at else "")
        + (f" / 最后错误：{rs.last_error[:200]}" if rs.last_error else "")
    )
    last_mem = ""
    if sup_mem and sup_mem.memory_md:
        # 取最后 600 字符
        last_mem = sup_mem.memory_md[-600:]
    return f"""
**{project.name}** (slug={project.slug})
runtime: {runtime}
最近 supervisor 记忆:
{last_mem or '（无）'}
""".strip()


async def classify_and_reply(
    db: AsyncSession,
    *,
    account: WechatClawbotAccount,
    wechat_user_id: str,
    user_text: str,
) -> dict[str, Any]:
    """主入口：分类用户消息 + 决定动作 + 准备回复文本。

    实现策略：
    - 先快速规则匹配 8 字符 request_id（hex）→ 锁定特定 pending
    - 否则调 LLM：给 LLM 该 reviewer 的所有 pending + 项目摘要，让它输出 JSON
    """
    import re

    projects = await list_reviewer_projects(db, account, wechat_user_id)
    pendings = await list_pending_for_reviewer(db, projects)

    # 1) 显式匹配 request_id 短码
    explicit_id_match = re.search(r"\b([a-f0-9]{8})\b", user_text.lower())
    target_pending: PendingApproval | None = None
    if explicit_id_match:
        candidate = explicit_id_match.group(1)
        target_pending = next(
            (p for p in pendings if p.request_id == candidate), None
        )

    # 2) 调 LLM 解析意图（提供完整上下文）
    # 限制最多 10 条 —— 一来防 prompt 爆 token，二来 daemon / builder 跑久了 pending 表会堆。
    # 若 target_pending 命中显式 request_id，优先放第一位。
    if target_pending is not None:
        pendings_for_prompt = [target_pending] + [p for p in pendings if p.id != target_pending.id][:9]
    else:
        pendings_for_prompt = pendings[:10]
    pending_lines: list[str] = []
    for p in pendings_for_prompt:
        project_name = await _project_name_by_id(db, p.mission_id)
        pending_lines.append(
            f"- request_id={p.request_id} | project={project_name} | 标题={p.title} | 选项={p.options}"
        )
    pending_brief = "\n".join(pending_lines) or "（无）"
    if len(pendings) > len(pendings_for_prompt):
        pending_brief += f"\n（另有 {len(pendings) - len(pendings_for_prompt)} 条 pending 未列出）"

    project_summaries: list[str] = []
    for p in projects[:5]:  # 限 5 个避免 prompt 太长
        try:
            project_summaries.append(await _project_summary(db, p))
        except Exception:  # noqa: BLE001
            pass
    summaries_str = "\n\n---\n\n".join(project_summaries) or "（无项目可访问）"

    target_hint = ""
    if target_pending is not None:
        target_hint = (
            f"\n**用户消息中已显式提到 request_id={target_pending.request_id} "
            f"(选项: {target_pending.options})。优先认定他在决定这条。**"
        )

    system = """你是 Colony 平台的微信助手。用户通过微信跟你对话；你只输出一个 JSON 对象，
不输出额外解释。可能的 intent：
- decide_approval: 用户明确要决定某条审批（自然语言：「OK 发吧」「行」「同意」「不行」「驳回」等）
- query_status: 用户问某项目当前状态、进度、最近在干啥
- chat_to_super: 用户想给某个 super 下指令/说话（不是决定审批、也不是单纯查状态），
  例如「让小红书号今天多发两条」「帮我写一篇关于咖啡的笔记」「告诉运营 super 暂停推广」
- unclear: 意图含糊，或同时有多条 pending 但用户没说哪条
JSON schema：
{
  "intent": "decide_approval" | "query_status" | "chat_to_super" | "unclear",
  "request_id": "<8字符 hex；intent=decide_approval 时必填>",
  "option": "<对应 pending.options 里某一项的精确文本；intent=decide_approval 时必填>",
  "target_project_slug": "<intent=query_status 或 chat_to_super 时，最匹配的项目 slug（语义匹配消息与项目）；不确定可留空>",
  "reply_text": "<给用户的简洁回复（中文，<=200 字，含 emoji 也行）>"
}
注意：
1. option 必须精确等于 pending.options 数组里某个字符串（用户说「ok」「行」时，应映射到「发布」「同意」之类的实际选项）
2. 只有 1 条 pending 时，「ok / 行 / 不行」之类直接对应那条
3. 多条 pending + 用户没说明 → intent=unclear，reply_text 列出候选问他指哪条
4. 用户问状态时，target_project_slug 写 query 的项目 slug（多项目则 reply 用 markdown 列每个状态）
5. chat_to_super 时，根据消息内容语义匹配最相关的项目写进 target_project_slug；多个都像就留空（平台会发菜单问用户）"""

    user_payload = f"""## 当前待审批列表
{pending_brief}

## 该用户可访问的项目状态摘要
{summaries_str}
{target_hint}

## 用户刚发来的消息
「{user_text}」

请输出 JSON。"""

    try:
        llm_out = await _invoke_intent_llm(db, system, user_payload)
        parsed = _parse_json_loose(llm_out)
        if not isinstance(parsed, dict) or "intent" not in parsed:
            raise ValueError(f"LLM 输出不是合法 intent JSON: {llm_out[:200]}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("[wechat_intent] LLM 意图解析失败")
        # 降级：如果只有 1 条 pending + 用户文本含「ok/同意/发布/yes」之类肯定词，按 PASS 处理
        return _fallback(user_text, pendings, str(exc))

    intent = parsed.get("intent", "unclear")
    reply_text = parsed.get("reply_text") or "已收到，正在处理。"

    if intent == "decide_approval":
        rid = parsed.get("request_id")
        opt = parsed.get("option")
        if not rid or not opt:
            return {"intent": "unclear", "reply_text": "未识别到 request_id 或选项，请明确告诉我。"}
        return {
            "intent": "decide_approval",
            "request_id": rid,
            "option": opt,
            "reply_text": reply_text,
        }
    if intent == "query_status":
        return {
            "intent": "query_status",
            "target_project_slug": parsed.get("target_project_slug"),
            "reply_text": reply_text,
        }
    if intent == "chat_to_super":
        # ADR-008 P4 · 自由消息路由：target_project_slug 作为 LLM 语义匹配提示交给 router
        return {
            "intent": "chat_to_super",
            "target_project_slug": parsed.get("target_project_slug"),
            "reply_text": reply_text,
        }
    return {"intent": "unclear", "reply_text": reply_text}


async def _project_name_by_id(db: AsyncSession, mission_id) -> str:
    p = await db.get(Mission, mission_id)
    return p.slug if p else str(mission_id)[:8]


async def _invoke_intent_llm(db: AsyncSession, system: str, user_payload: str) -> str:
    """调 default chat LLM 跑一次意图分类，返回文本。"""
    from app.services.llm_resolver import resolve_default_chat_llm

    import asyncio

    llm = await resolve_default_chat_llm(db)
    from langchain_core.messages import HumanMessage, SystemMessage

    # max_tokens 给足：qwen 等会先吐 thinking 再吐 JSON，默认 1024 常被 thinking 吃满 → 截断
    # → 触发 resilient 续写循环空转（多次整轮 LLM 调用，微信侧「半天没响应」）。给够一次出完。
    # 再套 25s 硬超时兜底：真卡住就快速降级到规则 fallback（_fallback 已能命中「确认/通过」等）。
    try:
        resp = await asyncio.wait_for(
            llm.ainvoke(
                [SystemMessage(content=system), HumanMessage(content=user_payload)],
                max_tokens=4096,
            ),
            timeout=25.0,
        )
    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
        logger.warning("[wechat_intent] 意图 LLM 超时/失败（%s），降级规则兜底", type(exc).__name__)
        return ""  # → _parse_json_loose("") 抛错 → classify_and_reply 走 _fallback
    text = getattr(resp, "content", None) or ""
    if isinstance(text, list):
        # multimodal content blocks; 抽 text
        text = "\n".join(
            seg.get("text", "") for seg in text if isinstance(seg, dict)
        )
    return str(text)


def _parse_json_loose(text: str) -> Any:
    """R3-5 · 委托 app/domain/wechat/intent_parser.parse_json_loose（thin wrapper）。"""
    from app.domain.wechat.intent_parser import parse_json_loose
    return parse_json_loose(text)


def _fallback(user_text: str, pendings: list[PendingApproval], err: str) -> dict[str, Any]:
    """R3-5 · 委托 app/domain/wechat/intent_parser.fallback_classify（纯核心，边界已单测）。"""
    from app.domain.wechat.intent_parser import fallback_classify
    return fallback_classify(user_text, pendings, err)


__all__ = ("classify_and_reply",)
