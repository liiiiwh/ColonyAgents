"""V7.5 · resolve_skill_scope · 内置 skill 的 (scope, intent) 单一映射。

migration 049 + seed_builtin_skills 共用，保证 fresh install 和已有 DB 一致。
scope ∈ {super, worker, builder, all}；intent ∈ {dispatch, memory, io, knowledge, ...}
"""
from __future__ import annotations

# super = 项目经理：只统筹调度 / 规划 / 审批 / 升级 / 质量门，**不碰业务执行**
_SUPER_DISPATCH = {
    "invoke_worker", "invoke_workers_parallel", "list_workers",
    "request_new_capability", "report_worker_issue", "list_supers", "emit_redirect_suggestion",
    "request_approval", "request_structured_input",
    "agent_protocol_propose", "agent_protocol_apply",
    "agent_protocol_revert", "agent_protocol_evaluate",
    "output_quality_check", "output_quality_check_force_override",  # PM 把关 worker 产出质量
    "mission_escalate_to_builder", "mission_escalation_dismiss",
    "mission_escalation_list",
    # ADR-024 S4 · super 自管调度（敏捷自迭代）：自己增删改本 mission 的调度，
    # 不再 escalate builder。护栏（数量/间隔/cron）在 schedule_create_tool 内（schedule_guard）。
    "schedule_create", "schedule_update", "schedule_delete",
    # ADR-025 · work-order 自驱续跑/收尾（按 kind 绑所有 super，服务层 work-order 自守卫）
    "optimization_continue", "optimization_done",
}
_SUPER_MEMORY = {
    "archive_to_knowledge", "experience_record", "promote_to_platform",
}
# super + worker 都需要的核心 → scope='all'：记忆/知识/决策 + workspace（通用产物区：
# super 写计划/读 worker 产出、worker 落业务产物，都用它；不是业务执行件，不归 worker-only）
_BOTH_CORE = {
    "memory_read", "memory_write", "memory_append",
    "knowledge_search", "platform_knowledge_search", "knowledge_index",
    "list_knowledge_bases", "record_decision",
    "workspace_read", "workspace_write", "workspace_write_batch", "workspace_list",
}
_WORKER_IO = {"return_result", "wechat_push_notification"}


def resolve_skill_scope(slug: str, category: str) -> tuple[str, str]:
    """返回 (scope, intent)。

    ADR-009 follow-up · super=项目经理只统筹。**默认 scope='worker'**（执行/IO/MCP/媒体/存储
    等业务落地类一律归 worker，不再污染 super）；只有显式 orchestration/规划/记忆/知识类才
    给 super 或 all。
    """
    if slug in _SUPER_DISPATCH:
        return "super", "dispatch"
    if slug in _SUPER_MEMORY:
        return "super", "memory"
    if slug in _BOTH_CORE:
        return "all", "memory"
    if slug in _WORKER_IO:
        return "worker", "io"
    if slug == "run_shell":
        # ADR-010 R3：通用 shell 仅 Builder（worker 泡在不可信业务内容里，不给 shell）
        return "builder", "dispatch"
    if (category or "").lower() in ("builder", "installer", "tester"):
        return "builder", "dispatch"
    return "worker", "io"  # 默认执行类 → worker（super 不再自动拿到 xiaohongshu-mcp 这类）
