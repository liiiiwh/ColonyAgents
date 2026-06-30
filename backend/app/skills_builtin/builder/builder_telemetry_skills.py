"""v6 · Builder-only worker_telemetry skill.

让 Builder LLM 在改进 worker 时不再"盲" —— 直接查 worker_invocation_log
拿到 success_rate / p95_ms / top_errors / 调用频次。（V7.4 · agent_activities 已退役）
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import StructuredTool
from sqlalchemy import text as _sql_text

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


def worker_telemetry_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _telemetry(capability: str = "", worker_agent_id: str = "",
                         window_days: int = 7) -> str:
        """v6 · Builder 看 worker 健康（成功率 / p95 / top_errors / 调用数 / artifact 数）。

        参数：
        - capability: capability slug（如 'xhs_ops'）；与 worker_agent_id 二选一
        - worker_agent_id: 指定 worker UUID
        - window_days: 默认 7

        返回：
        {
          worker_id, capability, window,
          overall: { total, completed, failed, success_rate, avg_duration_ms, p95_ms, total_tokens, ... }
          per_action: [{action, count, success_rate, avg_ms}],
          top_errors: [{err, count}]
        }
        """
        if ctx.db_factory is None:
            return json.dumps({"ok": False, "error": "缺 db_factory"})
        if not (capability or worker_agent_id):
            return json.dumps({"ok": False, "error": "至少传 capability 或 worker_agent_id"})

        async with ctx.db_factory() as db:
            # resolve worker_id
            wid = worker_agent_id
            if not wid:
                row = (await db.execute(_sql_text(
                    "SELECT id FROM agents WHERE kind='worker' AND capability=:cap AND is_enabled LIMIT 1"
                ), {"cap": capability})).scalar_one_or_none()
                if not row:
                    return json.dumps({"ok": False, "error": f"找不到 capability={capability} 的 enabled worker"})
                wid = str(row)

            try:
                overall = (await db.execute(_sql_text(f"""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                        SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                        SUM(CASE WHEN status='needs_clarification' THEN 1 ELSE 0 END) AS need_clar,
                        AVG(duration_ms) AS avg_ms,
                        percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
                        SUM(COALESCE(tokens_in,0)+COALESCE(tokens_out,0)) AS tokens,
                        SUM(artifact_count) AS artifacts
                      FROM worker_invocation_log
                     WHERE worker_agent_id = :wid
                       AND started_at >= now() - make_interval(days => :days)
                """), {"wid": wid, "days": window_days})).mappings().one()
                per_action = (await db.execute(_sql_text(f"""
                    SELECT action, COUNT(*) AS cnt,
                           SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS ok,
                           AVG(duration_ms) AS avg_ms
                      FROM worker_invocation_log
                     WHERE worker_agent_id=:wid
                       AND started_at >= now() - make_interval(days => :days)
                     GROUP BY action ORDER BY cnt DESC LIMIT 20
                """), {"wid": wid, "days": window_days})).mappings().all()
                top_errors = (await db.execute(_sql_text(f"""
                    SELECT SUBSTRING(error_msg, 1, 200) AS err, COUNT(*) AS cnt
                      FROM worker_invocation_log
                     WHERE worker_agent_id=:wid AND status='failed' AND error_msg IS NOT NULL
                       AND started_at >= now() - make_interval(days => :days)
                     GROUP BY err ORDER BY cnt DESC LIMIT 10
                """), {"wid": wid, "days": window_days})).mappings().all()
                # ADR-009 G1 · per-super 拆分：看「改了 worker 之后哪个 super 在掉链子」，
                # 聚合掩盖跨 super 损伤（A 全成功、B 全失败 → 整体 50% 看不出是 B 坏了）。
                per_super = (await db.execute(_sql_text(f"""
                    SELECT CAST(wil.super_mission_id AS TEXT) AS mission_id,
                           p.slug AS super_slug,
                           COUNT(*) AS cnt,
                           SUM(CASE WHEN wil.status='completed' THEN 1 ELSE 0 END) AS ok,
                           SUM(CASE WHEN wil.status='failed' THEN 1 ELSE 0 END) AS failed
                      FROM worker_invocation_log wil
                      LEFT JOIN missions p ON p.id = wil.super_mission_id
                     WHERE wil.worker_agent_id=:wid
                       AND wil.started_at >= now() - make_interval(days => :days)
                     GROUP BY wil.super_mission_id, p.slug ORDER BY failed DESC, cnt DESC LIMIT 30
                """), {"wid": wid, "days": window_days})).mappings().all()
            except Exception as e:
                logger.exception("[worker_telemetry] query failed")
                return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

        total = overall["total"] or 0
        completed = overall["completed"] or 0
        result = {
            "ok": True,
            "worker_id": wid,
            "capability": capability,
            "window_days": window_days,
            "overall": {
                "total": total,
                "completed": completed,
                "failed": overall["failed"] or 0,
                "needs_clarification": overall["need_clar"] or 0,
                "success_rate": (completed / total) if total > 0 else None,
                "avg_duration_ms": int(overall["avg_ms"]) if overall["avg_ms"] else None,
                "p95_duration_ms": int(overall["p95_ms"]) if overall["p95_ms"] else None,
                "total_tokens": int(overall["tokens"] or 0),
                "total_artifacts": int(overall["artifacts"] or 0),
            },
            "per_action": [dict(r) for r in per_action],
            "per_super": [
                {**dict(r), "success_rate": (r["ok"] / r["cnt"]) if r["cnt"] else None}
                for r in per_super
            ],
            "top_errors": [dict(r) for r in top_errors],
        }
        return json.dumps(result, ensure_ascii=False)
    return StructuredTool.from_function(
        coroutine=_telemetry,
        name="worker_telemetry",
        description=(
            "（Builder-only v6）拉某 worker 的运行健康度（成功率 / p95 / top_errors / token / artifact）。"
            "Builder 改 worker 协议、决定 upgrade-vs-new、或回答用户『为什么这个 worker 老超时』时必调。"
            "参数 capability(str) 或 worker_agent_id(str)，window_days(int=7)。"
        ),
    )
