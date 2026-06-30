"""R19 · 平台级 system_settings 管理 API。

- GET /api/admin/system-settings — 列全部 (admin only)
- PATCH /api/admin/system-settings/{key} — 更新单个 key 的 value（JSONB）
- 写后自动 invalidate compression_service 的进程内压缩配置缓存（V29）

主要用于 admin 在 UI 调整 compression.* 三件套 + dev.max_daemon_ticks (V56) + 其它后续平台配置。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text as _sql_text

from app.core.deps import AdminUser, DBSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/system-settings", tags=["admin-system-settings"])


def _coerce_int(v: Any, key: str) -> int:
    try:
        return int(v)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key} 必须为整数: {exc}")


class SystemSetting(BaseModel):
    key: str
    value: Any
    description: str | None = None
    updated_at: str | None = None
    updated_by: str | None = None


class SystemSettingPatch(BaseModel):
    value: Any


@router.get("", response_model=list[SystemSetting])
async def list_settings(db: DBSession, _admin: AdminUser) -> list[SystemSetting]:
    rows = (await db.execute(_sql_text(
        "SELECT key, value, description, to_char(updated_at,'YYYY-MM-DD HH24:MI:SS') AS updated_at, updated_by "
        "FROM system_settings ORDER BY key"
    ))).mappings().all()
    return [SystemSetting(**dict(r)) for r in rows]


# ── ADR-015 · 平台初始化向导 ──
class InstallStatus(BaseModel):
    is_install: bool  # ADR-019 修订：只认 LLM（语言不再阻塞安装）
    seed_language: str = "en"  # 系统 Agent 当前播种语言（非 gate，仅供前端提示）


@router.get("/install-status", response_model=InstallStatus)
async def install_status(db: DBSession, _admin: AdminUser) -> InstallStatus:
    """后台首启读：is_install=0 → 前端弹 onboarding（不可关闭直到默认模型配好）。"""
    from app.db.init_db import _is_platform_installed
    from app.domain.onboarding.seed_language import get_seed_language

    return InstallStatus(
        is_install=await _is_platform_installed(db),
        seed_language=await get_seed_language(db),
    )


# ── ADR-019(修订) · SeedLanguage（onboarding 选一次：播种系统 Agent 语言 + 设本人 UI 语言）──
class SeedLanguageBody(BaseModel):
    language: str


@router.post("/seed-language")
async def set_seed_language(
    body: SeedLanguageBody, db: DBSession, admin: AdminUser
) -> dict:
    """onboarding：选语言（en|zh）→ 记录 SeedLanguage + 按该语言重播两个用户对话 super
    （Builder Supervisor + Worker 优化）。前端另行 setLocale 设本人 UI 语言。"""
    import json as _json

    from app.core.system_settings import invalidate as _ss_invalidate
    from app.db.init_db import reseed_system_agents_language
    from app.domain.onboarding.seed_language import SEED_LANGUAGE_KEY, is_supported_language

    if not is_supported_language(body.language):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"language 必须是 en 或 zh，收到 {body.language!r}",
        )
    await db.execute(_sql_text(
        "INSERT INTO system_settings (key, value, description, updated_at, updated_by) "
        "VALUES (:k, CAST(:v AS jsonb), 'ADR-019 系统 Agent 播种语言', now(), :by) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now(), updated_by=EXCLUDED.updated_by"
    ), {"k": SEED_LANGUAGE_KEY, "v": _json.dumps(body.language), "by": str(admin.id)})
    await db.commit()
    _ss_invalidate()

    # 按语言重播两个用户对话 super（best-effort，不阻塞 onboarding）
    n = await reseed_system_agents_language(db, body.language)
    return {"ok": True, "seed_language": body.language, "reseeded": n}


@router.post("/install")
async def run_install(db: DBSession, _admin: AdminUser) -> dict:
    """一键注入平台初始化数据（Builder Mission / 自检会话 / catalog / KB），幂等，置 is_install=1。"""
    from app.db.init_db import run_platform_install
    result = await run_platform_install(db)
    return {**result, "is_install": True}


# ── ADR-016 · onboarding 默认模型（UI 选 + 自动 install）／续接① 设置页可见&可编辑 ──
class DefaultModelsBody(BaseModel):
    # 续接①：三个都可选（partial 编辑）。onboarding 仍同时传 supervisor+agent。
    supervisor_model_id: str | None = None
    agent_model_id: str | None = None
    # ADR-023 S7 · 默认 embedding 模型（可选）；不设则知识库无法建/召回
    embedding_model_id: str | None = None


class DefaultModelEntry(BaseModel):
    role: str  # supervisor | agent | embedding
    spec: str | None  # system_settings/env 里存的原始引用
    source: str  # system_settings | env | unresolved | none
    model_id: str | None  # 解析到的 LLMModel 主键
    label: str | None  # provider/model_id 展示名（绝不裸 uuid）


@router.get("/default-models", response_model=list[DefaultModelEntry])
async def get_default_models(db: DBSession, _admin: AdminUser) -> list[DefaultModelEntry]:
    """续接① · 设置页读：三个默认模型的有效值 + 来源（system_settings>env）。

    env-install 把默认模型写在 .env，从不回写 system_settings；此处统一解析出真实生效值，
    设置页据此始终能显示（即便来源是 env），并以 provider/model_id 形式展示，不暴露 uuid。
    """
    from app.domain.onboarding.default_model import describe_default_models

    return [DefaultModelEntry(**r) for r in await describe_default_models(db)]


@router.post("/default-models")
async def set_default_models(
    body: DefaultModelsBody, db: DBSession, admin: AdminUser
) -> dict:
    """onboarding：UI 选默认 supervisor/agent(/embedding) 模型 → 存 system_settings；
    续接①：设置页也复用此接口做 partial 编辑（只传要改的 role）。
    校验可解析且尚未安装 → 自动跑 platform-install（免手点向导）。返回 {ok, is_install}。"""
    import json as _json

    from app.core.system_settings import invalidate as _ss_invalidate
    from app.db.init_db import _is_platform_installed, run_platform_install
    from app.domain.onboarding.default_model import _resolve_spec

    # role → (system_settings key, description)
    _SPEC = {
        "supervisor": (body.supervisor_model_id, "default_supervisor_model_id", "ADR-016 onboarding 默认模型"),
        "agent": (body.agent_model_id, "default_agent_model_id", "ADR-016 onboarding 默认模型"),
        "embedding": (body.embedding_model_id, "default_embedding_model_id", "ADR-023 S7 默认 embedding 模型"),
    }
    provided = {role: v for role, v in _SPEC.items() if v[0]}
    if not provided:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少需提供一个默认模型")

    # 先校验每个传入的 model 都能解析（fail loud；不静默接受坏值）
    for role, (spec, _key, _desc) in provided.items():
        if await _resolve_spec(db, spec) is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{role}_model_id={spec!r} 解析不到 LLMModel；请先在 provider 下同步出该模型",
            )
    # upsert 传入的 key
    for role, (spec, key, desc) in provided.items():
        await db.execute(_sql_text(
            "INSERT INTO system_settings (key, value, description, updated_at, updated_by) "
            "VALUES (:k, CAST(:v AS jsonb), :d, now(), :by) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now(), updated_by=EXCLUDED.updated_by"
        ), {"k": key, "v": _json.dumps(spec), "d": desc, "by": str(admin.id)})
    await db.commit()
    _ss_invalidate()

    installed = await _is_platform_installed(db)

    # ADR-015/017 · 首次 onboarding 配好默认模型 → 立刻跑一次平台 worker 健康自检，
    # 让系统级自检 session 自动启动（之后按 6h 调度继续）。仅未安装时触发，避免设置页编辑也烧自检。
    if not installed:
        try:
            from app.core import bg_tasks
            from app.services.scheduler_service import _worker_health_job

            bg_tasks.spawn(_worker_health_job(), name="onboarding-health-tick")
        except Exception:  # noqa: BLE001
            logger.warning("[onboarding] 触发初始 worker 健康自检失败（不阻塞）", exc_info=True)

        result = await run_platform_install(db)
        return {"ok": True, "is_install": True, "auto_installed": True, **result}
    return {"ok": True, "is_install": True, "auto_installed": False}


@router.post("/__deprecate-project/{mission_id}")
async def deprecate_v1_project(
    mission_id: str,
    db: DBSession,
    admin: AdminUser,
) -> dict:
    """R12 · 把老 v1 project mark 为 deprecated（不删数据；migration 040 后置物理清理）。

    操作：
    - 把 lifecycle_status / runtime_status 切到 stopped（防 daemon 触发烧 token）
    - workflow_config.deprecated_at = now()（migration 040 据此筛删）
    - workflow_config.deprecated_by = admin.id
    """
    import json as _json
    import uuid as _uuid
    try:
        pid = _uuid.UUID(mission_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "mission_id 不是 UUID")
    # workflow_config 是 JSON 类型；jsonb_build_object 返回 jsonb，需要 cast 回 json
    result = await db.execute(_sql_text("""
        UPDATE missions
           SET lifecycle_status='stopped',
               runtime_status='stopped',
               workflow_config = (
                 COALESCE(workflow_config::jsonb, '{}'::jsonb)
                   || jsonb_build_object('deprecated_at', now()::text, 'deprecated_by', CAST(:by AS text))
               )::json
         WHERE id = :pid
         RETURNING id, slug, name, lifecycle_status
    """), {"pid": str(pid), "by": str(admin.id)})
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project 不存在")
    await db.commit()
    return {
        "ok": True,
        "project": {**dict(row), "id": str(row["id"])},
        "note": "已 mark deprecated；下次 migration 040 跑时物理删除。",
    }


@router.patch("/{key}", response_model=SystemSetting)
async def update_setting(
    key: str,
    payload: SystemSettingPatch,
    db: DBSession,
    admin: AdminUser,
) -> SystemSetting:
    # V28 限值：compression.threshold_tokens ≥ 1000；keep_recent ∈ [3, 100]；target_ratio ∈ [0.05, 0.95]
    v = payload.value
    if key == "compression.threshold_tokens":
        try:
            iv = int(v)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"threshold_tokens 必须为整数: {exc}")
        if iv < 1000:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "threshold_tokens 必须 ≥ 1000（V28）")
        v = iv
    elif key == "compression.keep_recent_messages":
        try:
            iv = int(v)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"keep_recent_messages 必须为整数: {exc}")
        if iv < 3 or iv > 100:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "keep_recent_messages 必须在 [3, 100]（V28）")
        v = iv
    elif key == "compression.target_ratio":
        try:
            fv = float(v)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"target_ratio 必须为数字: {exc}")
        if fv < 0.05 or fv > 0.95:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "target_ratio 必须在 [0.05, 0.95]")
        v = fv
    elif key == "dev.max_daemon_ticks":
        try:
            iv = int(v)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"max_daemon_ticks 必须为整数: {exc}")
        if iv < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "max_daemon_ticks 必须 ≥ 0（0=无上限）")
        v = iv
    elif key == "escalation.daily_quota_per_project":
        try:
            iv = int(v)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"daily_quota 必须为整数: {exc}")
        if iv < 1 or iv > 50:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "daily_quota 必须在 [1, 50]")
        v = iv
    elif key == "escalation.capability_quota_per_super":
        iv = _coerce_int(v, key)
        if iv < 1 or iv > 20:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "capability_quota_per_super 必须在 [1, 20]")
        v = iv
    elif key == "escalation.auto_dismiss_days":
        iv = _coerce_int(v, key)
        if iv < 1 or iv > 90:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "auto_dismiss_days 必须在 [1, 90]")
        v = iv
    elif key == "worker.max_clarification_rounds":
        iv = _coerce_int(v, key)
        if iv < 1 or iv > 10:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "max_clarification_rounds 必须在 [1, 10]")
        v = iv
    elif key == "worker.tool_message_max_kb":
        iv = _coerce_int(v, key)
        if iv < 5 or iv > 1024:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "tool_message_max_kb 必须在 [5, 1024]")
        v = iv
    elif key == "factory.worker_protocol_forbidden_words":
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "forbidden_words 必须是字符串数组")
    elif key == "compression.cache_ttl_seconds":
        iv = _coerce_int(v, key)
        if iv < 5 or iv > 3600:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "cache_ttl_seconds 必须在 [5, 3600]")
        v = iv
    elif key == "daemon.heartbeat_interval_seconds":
        iv = _coerce_int(v, key)
        if iv < 5 or iv > 600:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "heartbeat_interval_seconds 必须在 [5, 600]")
        v = iv
    elif key == "invoke_worker.timeout_seconds":
        iv = _coerce_int(v, key)
        if iv < 30 or iv > 3600:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "timeout_seconds 必须在 [30, 3600]")
        v = iv
    elif key == "invoke_worker.max_nesting_depth":
        iv = _coerce_int(v, key)
        if iv < 1 or iv > 5:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "max_nesting_depth 必须在 [1, 5]")
        v = iv
    elif key == "return_result.artifact_bytes_max_mb":
        iv = _coerce_int(v, key)
        if iv < 1 or iv > 500:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "artifact_bytes_max_mb 必须在 [1, 500]")
        v = iv
    elif key == "worker_invocation_log.ttl_days":
        iv = _coerce_int(v, key)
        if iv < 7 or iv > 365:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ttl_days 必须在 [7, 365]")
        v = iv
    elif key == "worker_invocation_log.archive_summary_enabled":
        if not isinstance(v, bool):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "archive_summary_enabled 必须是布尔")
    import json as _json
    result = await db.execute(_sql_text(
        "UPDATE system_settings SET value=CAST(:val AS jsonb), updated_at=now(), updated_by=:by "
        "WHERE key=:k RETURNING key, value, description, "
        "to_char(updated_at,'YYYY-MM-DD HH24:MI:SS') AS updated_at, updated_by"
    ), {"val": _json.dumps(v), "k": key, "by": str(admin.id)})
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"未找到 setting: {key}")
    await db.commit()
    # V29：invalidate 进程内 cache（压缩配置 + 全局 system_settings cache）
    try:
        from app.services.compression_service import invalidate_compression_platform_cache
        invalidate_compression_platform_cache()
    except Exception:
        pass
    try:
        from app.core.system_settings import invalidate as _ss_invalidate
        _ss_invalidate()
    except Exception:
        pass
    return SystemSetting(**dict(row))
