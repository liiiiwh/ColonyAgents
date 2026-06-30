"""R5-2 · DaemonPromptBuilder · daemon tick 的 5 段 prompt 拼装（纯）。

从 mission_daemon._assemble_super_prompt 搬出来，让 run_once 的 LLM invoke 路径更清晰。
§0/§1/§2 由 build_agent_executor 框架注入；本函数拼 §3 pending / §4 trigger / §5 runtime hint。
纯函数，无 DB。
"""
from __future__ import annotations

from typing import Any


def assemble_super_prompt(
    *,
    base_message: str,
    pending_user_msgs: list[dict],
    payload: dict,
    runtime_state: Any,
    cancel_resumed: bool = False,
) -> str:
    """把 super 一次 tick 的 prompt 按 5 段拼接成稳定 markdown（## §X 边界）。"""
    parts: list[str] = []
    parts.append("<!-- §0 system + §1 long_memory + §2 main_thread 由 executor 框架注入 -->")
    if pending_user_msgs:
        # V7.3 · 行为步道标签：用户消息优先响应（人在现场）
        sect3 = [
            "## §3 · [👤 用户实时插话·优先响应·人在现场]",
            "下列是用户在本轮刚发的消息。**先回应用户、纳入其诉求，再推进既定计划。**",
        ]
        for i, m in enumerate(pending_user_msgs, 1):
            ts = m.get("created_at")
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts or "?")
            content = (m.get("content") or "").strip()
            offloaded = (m.get("meta") or {}).get("v38_offloaded")
            tag = " [V38 已 offload]" if offloaded else ""
            sect3.append(f"\n### 👤 用户消息 #{i} ({ts_str}){tag}\n{content}\n")
        parts.append("\n".join(sect3))
    else:
        parts.append("<!-- §3 empty: 本次 tick 无用户新消息（[⏰ 定时自主运行]）-->")
    trig = (payload or {}).get("trigger") or "manual"
    task = (payload or {}).get("task") or "-"
    tg = (payload or {}).get("task_group") or "-"
    sched = (payload or {}).get("schedule_id") or "-"
    # §4 显式带上本轮 task（publish/patrol/report…），super 不必再从 cron 表达式猜「这轮该干啥」
    parts.append(
        f"## §4 · 触发元数据\n- trigger: `{trig}`\n- task: `{task}`\n- task_group: `{tg}`\n"
        f"- schedule_id: `{sched}`\n- tick #{getattr(runtime_state, 'run_count', '?')}\n"
        f"- base_message: {base_message[:200]}"
    )
    hint = []
    if cancel_resumed:
        hint.append("- 🛑 本次 tick 由用户消息触发（已 cancel 上次 tick）。先回应用户便条再继续既定计划。")
    last_err = getattr(runtime_state, "last_error", None)
    if last_err:
        hint.append(f"- ⚠️ 上一次 tick 报错：{str(last_err)[:200]}")
    if not hint:
        hint.append("- normal tick；按 protocol 推进。")
    parts.append("## §5 · 运行时提示\n" + "\n".join(hint))
    return "\n\n".join(parts)
