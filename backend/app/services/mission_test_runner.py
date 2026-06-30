"""M7: Mission smoke test runner — 沙盒克隆 + run_once + LLM judge。

设计：
- `clone_to_sandbox`：复制 mission 到新 slug `sandbox-<orig>-<unix_ts>`，
  status='draft'（不让普通用户看到）；记录到 MissionRunState 自然新建。
- `cleanup_sandbox`：直接 db.delete(sandbox_project)，FK CASCADE 把运行态 /
  记忆 / schedule 全清。
- `run_smoke_test`：clone → start → run_once → stop → cleanup → LLM judge → 返回结构化结果

LLM judge：
- 使用 settings.DEFAULT_AGENT_MODEL_ID 解出来的 model + provider api_key。失败 / 模型
  解不出 → verdict='needs_review' + 把原始数据返回让 Builder 自己判断。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mission import Mission
from app.services import mission_daemon, mission_service

logger = logging.getLogger(__name__)


# ─────────────────────────── sandbox ───────────────────────────
async def clone_to_sandbox(db: AsyncSession, mission_id: uuid.UUID) -> Mission:
    """复制 mission 到新 sandbox mission（ADR-027 · 无节点可拷）。同事务内 commit。"""
    orig = await mission_service.get_mission(db, mission_id)
    if orig is None:
        raise ValueError(f"Mission {mission_id} 不存在")
    ts = int(time.time())
    sb = Mission(
        name=f"[sandbox] {orig.name}",
        slug=f"sandbox-{orig.slug}-{ts}",
        description=f"自动 sandbox：源 project={orig.slug} 时间={ts}",
        status="draft",
        runtime_status="stopped",
        supervisor_agent_id=orig.supervisor_agent_id,
        auto_approve=orig.auto_approve,
        context_compression_threshold=orig.context_compression_threshold,
        workflow_config=dict(orig.workflow_config or {}),
        created_by=orig.created_by,
    )
    db.add(sb)
    await db.commit()
    await db.refresh(sb)
    return sb


async def cleanup_sandbox(db: AsyncSession, sandbox_project_id: uuid.UUID) -> bool:
    """删除 sandbox project（cascade delete run_state / memory / schedules）。"""
    proj = await db.get(Mission, sandbox_project_id)
    if proj is None:
        return False
    if not proj.slug.startswith("sandbox-"):
        # 防御：不允许用本函数删非 sandbox 项目
        raise ValueError(f"refuse to cleanup non-sandbox project slug={proj.slug!r}")
    await db.delete(proj)
    await db.commit()
    return True


# ─────────────────────────── LLM judge ───────────────────────────
_JUDGE_PROMPT = """你是 Colony Smoke Test 的 LLM Judge。
你不会真正执行业务，只看下面的"测试探针数据"和"acceptance 描述"，输出 JSON：

```json
{
  "verdict": "pass" | "fail" | "needs_review",
  "confidence": 0.0~1.0,
  "reasoning": "<= 200 字中文",
  "suggestions": ["可选改进 1", "可选改进 2"]
}
```

**判定规则（B5：daemon 真跑后用真信号）**：
- 有 validation_issues → fail
- run_count == 0 → fail（说明 daemon 根本没跑起来）
- last_error 非空 → fail，reasoning 指出错误根因
- supervisor_memory 为空（没调过 memory_append） → needs_review，建议加 memory 协议
- supervisor_memory 含「失败 / 错误 / 阻塞」关键词 → fail / needs_review
- supervisor_memory 含完整的 progress + next_step + 没有失败 → pass
- workspace_artifacts 非空（worker 真产出过东西）→ 提升 confidence
- 对照 acceptance 描述判断 reasoning（行为是否符合预期）"""


async def _llm_judge(
    scenario_text: str, probe: dict[str, Any]
) -> dict[str, Any]:
    """跑一次轻 LLM 让它判结果。失败时返回 needs_review。

    复用 llm_resolver（同一份 DEFAULT_AGENT_MODEL_ID 解析逻辑）。
    """
    try:
        from app.services.llm_resolver import resolve_default_chat_llm
        from app.db import session as _ds

        async with _ds.AsyncSessionLocal() as db:
            llm = await resolve_default_chat_llm(db)

        user_prompt = (
            "## acceptance 描述\n" + (scenario_text or "(空)") + "\n\n"
            "## 测试探针数据\n```json\n"
            + json.dumps(probe, ensure_ascii=False, indent=2)
            + "\n```"
        )
        from langchain_core.messages import HumanMessage, SystemMessage

        # 关掉 streaming 用 ainvoke 拿完整文本
        if hasattr(llm, "streaming"):
            try:
                llm.streaming = False
            except Exception:
                pass
        out = await llm.ainvoke(
            [SystemMessage(content=_JUDGE_PROMPT), HumanMessage(content=user_prompt)]
        )
        text = (getattr(out, "content", None) or "").strip()
        if not text:
            raise ValueError("judge 输出空内容")
        # 提取首个 JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0:
            raise ValueError(f"judge 输出无法解析 JSON: {text[:200]}")
        verdict_obj = json.loads(text[start : end + 1])
        if "verdict" not in verdict_obj:
            raise ValueError(f"judge 输出缺 verdict 字段: {verdict_obj}")
        return verdict_obj
    except Exception as exc:  # noqa: BLE001
        logger.warning("[smoke-test] LLM judge 失败：%s（降级 needs_review）", exc)
        return {
            "verdict": "needs_review",
            "confidence": 0.0,
            "reasoning": f"LLM judge 失败：{exc}",
            "suggestions": [],
        }


# ─────────────────────────── main entry ───────────────────────────
async def run_smoke_test(
    db: AsyncSession,
    mission_id: uuid.UUID,
    *,
    scenario_text: str = "",
) -> dict[str, Any]:
    """对 mission_id 跑 smoke test。返回结构化结果。"""
    orig = await mission_service.get_mission(db, mission_id)
    if orig is None:
        raise ValueError(f"Mission {mission_id} 不存在")

    validation_issues = mission_service.validate_workflow(orig)

    sandbox: Mission | None = None
    probe: dict[str, Any] = {
        "source_project_id": str(mission_id),
        "source_slug": orig.slug,
        "validation_issues": validation_issues,
        "ran_run_once": False,
        "run_count": 0,
        "last_error": None,
        "current_step": None,
    }

    if not validation_issues:
        try:
            sandbox = await clone_to_sandbox(db, mission_id)
            probe["sandbox_project_id"] = str(sandbox.id)
            probe["sandbox_slug"] = sandbox.slug

            await mission_daemon.start(db, sandbox.id)
            res = await mission_daemon.run_once(db, sandbox.id, payload={"smoke": True})
            probe["ran_run_once"] = True
            probe["run_once_result"] = res
            rs = await mission_daemon.get_runtime(db, sandbox.id)
            probe["run_count"] = rs.run_count
            probe["last_error"] = rs.last_error
            probe["current_step"] = rs.current_step
            # B5：抽真实信号——MissionAgentMemory + sandbox daemon workspace artifacts
            try:
                from app.models.mission import MissionAgentMemory

                mem_rows = (
                    await db.execute(
                        select(MissionAgentMemory).where(
                            MissionAgentMemory.mission_id == sandbox.id
                        )
                    )
                ).scalars().all()
                probe["supervisor_memory"] = next(
                    (r.memory_md for r in mem_rows if r.agent_node_name == "supervisor"),
                    "",
                )[:3000]
                probe["worker_memories"] = {
                    r.agent_node_name: (r.memory_md or "")[:1000]
                    for r in mem_rows if r.agent_node_name != "supervisor"
                }
                # ADR-018 mission-only · daemon workspace 挂 Mission(Mission) 上
                ws = sandbox.workspace or {}
                if ws:
                    probe["workspace_artifacts"] = {
                        node_name: [
                            {"label": a.get("label"), "type": a.get("type")}
                            for a in (entry.get("artifacts") or [])
                            if isinstance(a, dict)
                        ]
                        for node_name, entry in ws.items()
                        if isinstance(entry, dict)
                    }
            except Exception:  # noqa: BLE001
                logger.exception("[smoke-test] probe 抽真实信号失败（继续）")
        except Exception as exc:  # noqa: BLE001
            probe["sandbox_run_error"] = str(exc)
            logger.exception("[smoke-test] sandbox run 失败 project=%s", mission_id)
        finally:
            if sandbox is not None:
                try:
                    await mission_daemon.stop(db, sandbox.id)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await cleanup_sandbox(db, sandbox.id)
                except Exception:  # noqa: BLE001
                    logger.exception("[smoke-test] cleanup_sandbox 失败 %s", sandbox.id)

    judge = await _llm_judge(scenario_text, probe)
    return {
        "probe": probe,
        "judge": judge,
    }
