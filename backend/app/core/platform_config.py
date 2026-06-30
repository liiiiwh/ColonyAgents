"""R3-6 · 类型化 PlatformConfig · 集中所有 admin-tunable 运行配置。

之前 14 个 config key 以 magic string 散在 6 个文件里调 system_settings.get_int(...)；
key 拼错会静默落 default，同 key 不同 caller 还可能给不同 default。

现在：一个 dataclass 集中 key/default/类型；`await PlatformConfig.load(db)` 一次读全部。
caller 改 `cfg.worker_max_clarification_rounds`（IDE 补全 + typo 编译期挂）。

新增配置项流程：① 这里加一个字段 + (key, kind, default) ② caller 用属性。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import system_settings as _ss


# (attr_name, settings_key, kind, default)
_SPEC: list[tuple[str, str, Literal["int", "float", "bool"], object]] = [
    # invoke_worker（V17/V37/V38）
    ("invoke_worker_max_nesting_depth", "invoke_worker.max_nesting_depth", "int", 2),
    ("invoke_worker_timeout_seconds", "invoke_worker.timeout_seconds", "int", 600),
    ("worker_max_clarification_rounds", "worker.max_clarification_rounds", "int", 3),
    ("worker_tool_message_max_kb", "worker.tool_message_max_kb", "int", 50),
    ("worker_invocation_log_ttl_days", "worker_invocation_log.ttl_days", "int", 90),
    ("return_result_artifact_bytes_max_mb", "return_result.artifact_bytes_max_mb", "int", 100),
    # super 实时对话
    ("super_user_chat_cancel_timeout_seconds", "super.user_chat_cancel_timeout_seconds", "float", 10.0),
    ("super_max_pending_msgs_per_super", "super.max_pending_msgs_per_super", "int", 20),
    ("super_pending_msg_max_kb_per_msg", "super.pending_msg_max_kb_per_msg", "int", 50),
    ("super_auto_trigger_on_user_msg", "super.auto_trigger_on_user_msg", "bool", True),
    # escalation（V16）
    ("escalation_capability_quota_per_super", "escalation.capability_quota_per_super", "int", 3),
    ("escalation_auto_dismiss_days", "escalation.auto_dismiss_days", "int", 7),
    # 平台开关
    ("live_events_enabled", "live_events_enabled", "bool", True),
    ("memory_edit_enabled", "memory_edit_enabled", "bool", False),
]


@dataclass(frozen=True)
class PlatformConfig:
    invoke_worker_max_nesting_depth: int
    invoke_worker_timeout_seconds: int
    worker_max_clarification_rounds: int
    worker_tool_message_max_kb: int
    worker_invocation_log_ttl_days: int
    return_result_artifact_bytes_max_mb: int
    super_user_chat_cancel_timeout_seconds: float
    super_max_pending_msgs_per_super: int
    super_pending_msg_max_kb_per_msg: int
    super_auto_trigger_on_user_msg: bool
    escalation_capability_quota_per_super: int
    escalation_auto_dismiss_days: int
    live_events_enabled: bool
    memory_edit_enabled: bool

    @classmethod
    async def load(cls, db: AsyncSession) -> "PlatformConfig":
        """一次读全部 key（走 system_settings 缓存）；DB 缺 key 用 dataclass 默认。"""
        values: dict[str, object] = {}
        for attr, key, kind, default in _SPEC:
            if kind == "int":
                values[attr] = await _ss.get_int(db, key, default)  # type: ignore[arg-type]
            elif kind == "float":
                values[attr] = await _ss.get_float(db, key, default)  # type: ignore[arg-type]
            else:
                values[attr] = await _ss.get_bool(db, key, default)  # type: ignore[arg-type]
        return cls(**values)  # type: ignore[arg-type]
