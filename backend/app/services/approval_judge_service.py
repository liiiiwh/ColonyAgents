"""ADR-028 D1（修订）· 人工门唯一裁决：request_approval 服务端自动咨询 approval_judge。

设计变更（用户 grill 2026-06-30）：`request_approval` **不再接收 force_human 参数**。
是否必须真人审批，**完全由系统级 approval_judge worker 判定**——request_approval 在落卡前
服务端自动调它，喂入当前上下文 + auto_approve 开启状态，拿结构化 {must_human}。
must_human=True → 强制停（凌驾 auto_approve）；False → 按 auto_approve 走。

为什么放服务端而非靠 super 自觉：实测（励志文案 super）super 会"咨询了 judge 但忘了把
must_human 传成 force_human"→ auto_approve 把人工门放行（用户 #1 投诉复现）。把"咨询 + 套用"
变成 request_approval 内部确定性步骤，super 想漏也漏不掉。

fail-safe：approval_judge 不可用 / LLM 输出无法解析 → 默认 must_human=True（存疑即停，
符合"人工审核不管 auto 都停"原则）。测试中由 conftest autouse mock 旁路，避免每次真起 LLM。
"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.mission import Mission

logger = logging.getLogger(__name__)

APPROVAL_JUDGE_CAPABILITY = "approval_judge"


def _parse_must_human(text: str) -> tuple[bool, str]:
    """从 approval_judge LLM 自由文本里抽 {must_human, reason}；抽不到 → fail-safe (True)。"""
    if not text:
        return True, "empty judge output → fail-safe stop"
    # 找最后一个 JSON 对象（judge 可能先分析再给 JSON）
    candidates = re.findall(r"\{[^{}]*\"must_human\"[^{}]*\}", text, re.DOTALL)
    for raw in reversed(candidates):
        try:
            obj = json.loads(raw)
            mh = obj.get("must_human")
            if isinstance(mh, bool):
                return mh, str(obj.get("reason") or "")
        except (ValueError, TypeError):
            continue
    # 兜底关键词
    low = text.lower()
    if '"must_human": true' in low or "must_human=true" in low:
        return True, "keyword match true"
    if '"must_human": false' in low or "must_human=false" in low:
        return False, "keyword match false"
    return True, "unparseable judge output → fail-safe stop"


async def judge_must_human(
    db: AsyncSession,
    mission: Mission,
    *,
    title: str,
    message: str,
    options: list[str],
    auto_approve_on: bool,
    context: str = "",
) -> tuple[bool, str]:
    """request_approval 服务端调用：approval_judge 判本次审批是否必须真人。

    返回 (must_human, reason)。任何异常 → (True, reason) 兜底停。
    """
    try:
        judge = (await db.execute(
            select(Agent).where(
                Agent.capability == APPROVAL_JUDGE_CAPABILITY,
                Agent.is_enabled.is_(True),
            ).limit(1)
        )).scalar_one_or_none()
        if judge is None:
            logger.warning("[approval_judge] worker 未就绪 → fail-safe must_human=True")
            return True, "approval_judge worker 未就绪 → 保守停"

        from app.services import agent_service
        from app.skills_builtin.context import BuiltinToolContext
        from app.db import session as _db_session
        import langchain_core.messages as _msgs

        ctx = BuiltinToolContext(
            mission_id=mission.id,
            thread_key="health",  # 机器对机器判定，不污染主线程
            agent_node_name="approval_judge",
            db_factory=_db_session.AsyncSessionLocal,
        )
        executor = await agent_service.build_agent_executor(db, judge, ctx=ctx)
        judge_input = json.dumps({
            "title": title,
            "message": message[:1500],
            "options": options,
            "context": context[:1000],
            "auto_approve_on": auto_approve_on,
        }, ensure_ascii=False)
        result = await executor.ainvoke({"messages": [
            _msgs.HumanMessage(content=(
                "judge this approval request. Inputs:\n" + judge_input
                + "\n\nReturn ONLY the JSON verdict {\"must_human\": <bool>, \"reason\": \"...\"}."
            ))
        ]})
        msgs = (result or {}).get("messages") or []
        text = ""
        for m in reversed(msgs):
            c = getattr(m, "content", None)
            if isinstance(c, str) and c.strip():
                text = c
                break
        must_human, reason = _parse_must_human(text)
        logger.info("[approval_judge] must_human=%s reason=%s title=%s", must_human, reason[:80], title[:40])
        return must_human, reason
    except Exception:  # noqa: BLE001
        logger.exception("[approval_judge] 判定失败 → fail-safe must_human=True")
        return True, "approval_judge 判定异常 → 保守停"
