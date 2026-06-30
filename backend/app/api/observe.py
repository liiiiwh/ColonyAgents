"""v3 观察 API（R23 super-centric + R26 worker-centric）。

R23 · /api/super/{slug}/
  - threads     : 列 super 的所有 (super, worker) thread + 摘要
  - artifacts   : 跨 thread 聚合的产出物 (paginated)
  - stats       : 大盘统计（调用次数 / 成功率 / token 消耗 / 失败 top）
  - export thread : markdown / json 导出（V40：base64 替换为 S3 URL）

R26 · /api/workers
  - GET /             : 列全部 kind='worker' agent + 摘要
  - GET /{worker_id}  : 详情 + capability_contract
  - GET /{worker_id}/invocations : 调用列表分页 (V46 limit max 200)
  - GET /{worker_id}/artifacts   : 该 worker 历史交付聚合
  - GET /{worker_id}/stats       : 大盘 + 副指标（per super, per action, top errors）
  - GET /{worker_id}/overrides   : 各 super 的 per-super override 列表
  - GET /{worker_id}/protocol-history : 协议版本历史
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select, text as _sql_text
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DBSession
from app.models.agent import Agent
from app.models.mission import Mission

router = APIRouter(tags=["observe-v3"])


def _jnum(v: Any) -> Any:
    """Decimal → JSON-friendly number. Postgres AVG/SUM/percentile return NUMERIC,
    which SQLAlchemy yields as Decimal and FastAPI serializes as a **string**
    (e.g. "22405.000000000000", "0E-20"). The frontend then calls .toFixed() on a
    string and throws (perf tab crash). Coerce to int/float here; non-Decimal passes through."""
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f == int(f) else f
    return v


def _jrow(row: Any) -> dict:
    """dict(mappings row) with every Decimal value coerced to a JSON number."""
    return {k: _jnum(v) for k, v in dict(row).items()}


# ─────────────────────────── R23 · super ───────────────────────────


def _worker_id_from_thread_key(tk: str) -> str | None:
    """ADR-024 #8 · 从 worker:{super_id}:{worker_id} 提取 worker_id（全 UUID）。

    非 worker 线程（main / health）或格式不全 → None。
    """
    if not tk or not tk.startswith("worker:"):
        return None
    parts = tk.split(":")
    return parts[2] if len(parts) >= 3 and parts[2] else None


def _worker_thread_title(thread_key: str, worker_id: str | None, label: str | None) -> str:
    """worker 线程显示标题：永不暴露裸 uuid。

    - 存在的 worker → agent 名（capability）；
    - 已删 worker（label 缺失但有 worker_id）→「Worker · 短id（已删除）」（不暴露 super_id/全 uuid）；
    - 真畸形键 → 兜底原 thread_key。
    """
    if label:
        return label
    if worker_id:
        return f"Worker · {worker_id[:8]}（已删除）"
    return thread_key


@router.get("/api/super/{slug}/threads")
async def super_threads(slug: str, db: DBSession, _u: CurrentUser) -> dict:
    """列出该 mission (按 project.slug) 的所有 thread（ADR-018 mission-only：纯 (mission_id, thread_key)）。

    thread 直接从 messages 按 thread_key 聚合，不再经 sessions/session_branches。水位线取
    thread_compression_state。thread_kind 由 thread_key 反推（'main'→super_main_runtime /
    'health'→worker_health / 'worker:*'→super_worker_thread / 其他→orchestrator）。"""
    proj = (await db.execute(
        select(Mission).where(Mission.slug == slug)
    )).scalar_one_or_none()
    if proj is None:
        # 无同名 mission：可能是「无 standing mission 的 super」入口（如 Builder）。按 super slug
        # 解析，返回空壳（supervisor_agent_id + 空 threads，mission_id=None）→ 工作台直接显示空
        # mission 列表并自动弹「新建 Mission」，省掉中间那层 /super 角色页。
        _sup_agent = (await db.execute(
            select(Agent).where(Agent.kind == "super", Agent.slug == slug)
        )).scalar_one_or_none()
        if _sup_agent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"slug={slug} 既无 mission 也无同名 super")
        return {
            "mission_id": None,
            "slug": slug,
            "name": _sup_agent.display_name or _sup_agent.name,
            "lifecycle_status": None,
            "paused_reason": None,
            "supervisor_agent_id": str(_sup_agent.id),
            "super_slug": _sup_agent.slug or _sup_agent.name,
            "super_name": _sup_agent.display_name or _sup_agent.name,
            "threads": [],
        }
    super_id = proj.supervisor_agent_id
    rows = (await db.execute(_sql_text("""
        SELECT m.thread_key,
               COUNT(m.id) AS msg_count,
               MIN(m.created_at) AS created_at,
               MAX(m.created_at) AS last_msg_at,
               tcs.compressed_up_to_at
          FROM messages m
          LEFT JOIN thread_compression_state tcs
                 ON tcs.mission_id = m.mission_id AND tcs.thread_key = m.thread_key
         WHERE m.mission_id = :pid AND m.thread_key IS NOT NULL
         GROUP BY m.thread_key, tcs.compressed_up_to_at
         ORDER BY MAX(m.created_at) DESC NULLS LAST
         LIMIT 50
    """), {"pid": str(proj.id)})).mappings().all()

    def _kind(tk: str) -> str:
        # ADR-020 · 只有三类干净键；super- 仅作旧数据兼容识别（清理前的过渡）
        if tk == "main":
            return "super_main_runtime"
        if tk == "health":
            return "worker_health"
        if tk.startswith("worker:") or tk.startswith("super-"):
            return "super_worker_thread"
        return "other"

    # ADR-024 #8 · worker 线程显示可读名（agent.name + capability），不再裸 UUID
    import uuid as _uuid
    _wids = {w for r in rows if (w := _worker_id_from_thread_key(r["thread_key"]))}
    _labels: dict[str, str] = {}
    if _wids:
        _valid = []
        for w in _wids:
            try:
                _valid.append(_uuid.UUID(w))
            except (ValueError, AttributeError):
                pass
        if _valid:
            for a in (await db.execute(select(Agent).where(Agent.id.in_(_valid)))).scalars().all():
                _cap = f"（{a.capability}）" if getattr(a, "capability", None) else ""
                _labels[str(a.id)] = f"{a.name}{_cap}"

    threads = []
    for r in rows:
        tk = r["thread_key"]
        _w = _worker_id_from_thread_key(tk)
        _title = "主线" if tk == "main" else _worker_thread_title(tk, _w, _labels.get(_w or ""))
        threads.append({
            # ADR-018: thread 的标识就是 thread_key（前端用它拉消息 / 导出）
            "thread_key": tk,
            "thread_kind": _kind(tk),
            "title": _title,
            "worker_id": _w,
            "msg_count": r["msg_count"] or 0,
            "last_msg_at": r["last_msg_at"].isoformat() if r["last_msg_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "compressed_up_to_at": r["compressed_up_to_at"].isoformat() if r["compressed_up_to_at"] else None,
        })
    # super 身份（标题/路由用）：优先 agent.slug/display_name，回退 agent.name
    _sup = await db.get(Agent, super_id) if super_id else None
    return {
        "mission_id": str(proj.id),
        "slug": proj.slug,
        "name": proj.name,
        "lifecycle_status": proj.lifecycle_status,
        "paused_reason": proj.paused_reason,
        "supervisor_agent_id": str(super_id),
        "super_slug": (getattr(_sup, "slug", None) or getattr(_sup, "name", None)) if _sup else None,
        "super_name": (getattr(_sup, "display_name", None) or getattr(_sup, "name", None)) if _sup else None,
        "threads": threads,
    }


@router.get("/api/super/{slug}/artifacts")
async def super_artifacts(
    slug: str,
    db: DBSession,
    _u: CurrentUser,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),  # V46 / V39
    media_type: str | None = None,
    worker_id: str | None = None,
) -> dict:
    proj = (await db.execute(
        select(Mission).where(Mission.slug == slug)
    )).scalar_one_or_none()
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project 不存在")
    # 扫该 super 关联 thread 的 ToolMessage 里含 artifact_url 的
    # （worker invocation_log 提供 artifact_count；artifact 实物在 messages.meta）
    params: dict[str, Any] = {"pid": str(proj.id), "limit": limit, "off": (page - 1) * limit}
    where_extra = ""
    if media_type:
        where_extra += " AND meta->>'media_type' = :media_type"
        params["media_type"] = media_type
    if worker_id:
        where_extra += " AND meta->>'worker_agent_id' = :worker_id"
        params["worker_id"] = worker_id
    rows = (await db.execute(_sql_text(f"""
        SELECT m.id AS message_id, m.created_at,
               m.meta->>'artifact_url' AS artifact_url,
               m.meta->>'media_type' AS media_type,
               m.meta->>'worker_agent_id' AS worker_id,
               m.meta->>'action' AS action,
               m.meta->'artifact_meta' AS artifact_meta
          FROM messages m
         WHERE m.mission_id = :pid
           AND m.meta ? 'artifact_url'
           {where_extra}
         ORDER BY m.created_at DESC
         LIMIT :limit OFFSET :off
    """), params)).mappings().all()
    return {
        "page": page,
        "limit": limit,
        "items": [
            {
                "message_id": str(r["message_id"]),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "artifact_url": r["artifact_url"],
                "media_type": r["media_type"],
                "worker_id": r["worker_id"],
                "action": r["action"],
                "artifact_meta": r["artifact_meta"],
            }
            for r in rows
        ],
    }


@router.get("/api/super/{slug}/stats")
async def super_stats(
    slug: str,
    db: DBSession,
    _u: CurrentUser,
    window: str = Query("7d", pattern="^(1d|7d|30d|all)$"),
) -> dict:
    proj = (await db.execute(
        select(Mission).where(Mission.slug == slug)
    )).scalar_one_or_none()
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project 不存在")
    window_sql = {
        "1d": "AND started_at >= now() - interval '1 day'",
        "7d": "AND started_at >= now() - interval '7 days'",
        "30d": "AND started_at >= now() - interval '30 days'",
        "all": "",
    }[window]
    rows = (await db.execute(_sql_text(f"""
        SELECT status, COUNT(*) AS cnt,
               AVG(duration_ms) AS avg_ms,
               SUM(COALESCE(tokens_in,0) + COALESCE(tokens_out,0)) AS tokens,
               SUM(artifact_count) AS artifacts
          FROM worker_invocation_log
         WHERE super_mission_id = :pid
           {window_sql}
         GROUP BY status
    """), {"pid": str(proj.id)})).mappings().all()
    by_status = {r["status"]: _jrow(r) for r in rows}
    per_worker = (await db.execute(_sql_text(f"""
        SELECT worker_agent_id, COUNT(*) AS cnt,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS ok,
               AVG(duration_ms) AS avg_ms
          FROM worker_invocation_log
         WHERE super_mission_id = :pid
           {window_sql}
         GROUP BY worker_agent_id
         ORDER BY cnt DESC LIMIT 20
    """), {"pid": str(proj.id)})).mappings().all()
    top_errors = (await db.execute(_sql_text(f"""
        SELECT SUBSTRING(error_msg, 1, 120) AS err, COUNT(*) AS cnt
          FROM worker_invocation_log
         WHERE super_mission_id = :pid AND status='failed' AND error_msg IS NOT NULL
           {window_sql}
         GROUP BY err ORDER BY cnt DESC LIMIT 10
    """), {"pid": str(proj.id)})).mappings().all()
    return {
        "mission_id": str(proj.id),
        "window": window,
        "by_status": by_status,
        "per_worker": [_jrow(r) for r in per_worker],
        "top_errors": [_jrow(r) for r in top_errors],
    }


@router.get("/api/super/{slug}/threads/{thread_key}/export")
async def export_thread(
    slug: str,
    thread_key: str,
    db: DBSession,
    _u: CurrentUser,
    format: str = Query("markdown", pattern="^(markdown|json)$"),
) -> dict | str:
    """V40 导出 thread（ADR-018：按 (mission_id, thread_key) 直接读）。"""
    from app.services import messaging_service as _ss

    proj = (await db.execute(
        select(Mission).where(Mission.slug == slug)
    )).scalar_one_or_none()
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"slug={slug} project 不存在")
    msgs = await _ss.list_thread_messages(db, proj.id, thread_key, include_compressed=True)
    if format == "json":
        return {
            "thread_key": thread_key,
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "meta": m.meta,
                    "created_at": m.created_at.isoformat(),
                }
                for m in msgs
            ],
        }
    # markdown
    parts: list[str] = [f"# Thread Export {thread_key}\n"]
    for m in msgs:
        parts.append(f"\n## [{m.created_at.isoformat()}] {m.role}\n")
        meta = m.meta or {}
        if isinstance(meta, dict) and meta.get("artifact_url"):
            parts.append(f"\n_artifact_: {meta['artifact_url']}\n")
        else:
            body = (m.content or "")[:8000]
            parts.append(f"\n{body}\n")
    return "\n".join(parts)


@router.delete("/api/super/{slug}/threads/{thread_key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(slug: str, thread_key: str, db: DBSession, _u: CurrentUser) -> None:
    """删一个 thread 的全部上下文（ADR-018 mission-only：按 (mission_id, thread_key)）。

    删 messages + thread_compression_state + thread_agent_memories；daemon 主线删后下次 tick 自然重建。"""
    from sqlalchemy import delete as _delete

    from app.models.message import Message, ThreadAgentMemory, ThreadCompressionState

    proj = (await db.execute(
        select(Mission).where(Mission.slug == slug)
    )).scalar_one_or_none()
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"slug={slug} project 不存在")
    for model in (Message, ThreadCompressionState, ThreadAgentMemory):
        await db.execute(
            _delete(model).where(model.mission_id == proj.id, model.thread_key == thread_key)
        )
    await db.commit()


# ─────────────────────────── R26 · worker ───────────────────────────

@router.get("/api/workers")
async def list_workers_with_stats(db: DBSession, _u: CurrentUser) -> list[dict]:
    rows = (await db.execute(_sql_text("""
        SELECT a.id, a.name, a.capability, a.kind, a.is_system,
               a.extra_config->'capability_contract'->>'version' AS contract_version,
               COALESCE((
                   SELECT COUNT(*) FROM worker_invocation_log
                    WHERE worker_agent_id=a.id AND started_at >= now() - interval '30 days'
               ), 0) AS invocations_30d,
               COALESCE((
                   SELECT COUNT(*) FROM worker_invocation_log
                    WHERE worker_agent_id=a.id AND started_at >= now() - interval '30 days'
                      AND status='completed'
               ), 0) AS ok_30d
          FROM agents a
         WHERE a.kind = 'worker'
         ORDER BY a.capability NULLS LAST, a.name
    """))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/api/workers/{worker_id}")
async def get_worker(worker_id: uuid.UUID, db: DBSession, _u: CurrentUser) -> dict:
    agent = await db.get(Agent, worker_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "worker 不存在")
    return {
        "id": str(agent.id),
        "name": agent.name,
        "kind": agent.kind,
        "capability": agent.capability,
        "description": agent.description,
        "category": agent.category,
        "max_iterations": agent.max_iterations,
        "enable_thinking": agent.enable_thinking,
        "thinking_level": agent.thinking_level,
        "is_enabled": agent.is_enabled,
        "extra_config": agent.extra_config,
        "capability_contract": (agent.extra_config or {}).get("capability_contract"),
    }


@router.get("/api/workers/{worker_id}/invocations")
async def worker_invocations(
    worker_id: uuid.UUID,
    db: DBSession,
    _u: CurrentUser,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    since_days: int = Query(30, ge=1, le=365),
    super_id: uuid.UUID | None = None,
) -> dict:
    params: dict[str, Any] = {
        "wid": str(worker_id), "limit": limit, "off": (page - 1) * limit, "days": since_days,
    }
    where = ["worker_agent_id = :wid", "started_at >= now() - make_interval(days => :days)"]
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter
    if super_id:
        where.append("super_agent_id = :sid")
        params["sid"] = str(super_id)
    sql = f"""
        SELECT id, super_agent_id, super_mission_id, action,
               started_at, finished_at, duration_ms, status, error_msg,
               tokens_in, tokens_out, artifact_count, artifact_total_bytes,
               needs_clarification_round
          FROM worker_invocation_log
         WHERE {' AND '.join(where)}
         ORDER BY started_at DESC
         LIMIT :limit OFFSET :off
    """
    rows = (await db.execute(_sql_text(sql), params)).mappings().all()
    return {
        "page": page,
        "limit": limit,
        "items": [
            {
                **dict(r),
                "id": str(r["id"]),
                "super_agent_id": str(r["super_agent_id"]),
                "super_mission_id": str(r["super_mission_id"]) if r["super_mission_id"] else None,
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            }
            for r in rows
        ],
    }


@router.get("/api/workers/{worker_id}/stats")
async def worker_stats(
    worker_id: uuid.UUID,
    db: DBSession,
    _u: CurrentUser,
    window: str = Query("7d", pattern="^(1d|7d|30d|all)$"),
) -> dict:
    window_sql = {
        "1d": "AND started_at >= now() - interval '1 day'",
        "7d": "AND started_at >= now() - interval '7 days'",
        "30d": "AND started_at >= now() - interval '30 days'",
        "all": "",
    }[window]
    overall = (await db.execute(_sql_text(f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS ok,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
               SUM(CASE WHEN status='needs_clarification' THEN 1 ELSE 0 END) AS need_clar,
               AVG(duration_ms) AS avg_ms,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99_ms,
               SUM(COALESCE(tokens_in,0) + COALESCE(tokens_out,0)) AS tokens,
               AVG(COALESCE(tokens_in,0) + COALESCE(tokens_out,0)) AS avg_tokens,
               SUM(artifact_count) AS artifacts,
               SUM(artifact_total_bytes) AS artifact_bytes,
               COUNT(DISTINCT super_agent_id) AS active_supers
          FROM worker_invocation_log
         WHERE worker_agent_id = :wid {window_sql}
    """), {"wid": str(worker_id)})).mappings().one()
    per_action = (await db.execute(_sql_text(f"""
        SELECT action, COUNT(*) AS cnt,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS ok,
               AVG(duration_ms) AS avg_ms
          FROM worker_invocation_log
         WHERE worker_agent_id = :wid {window_sql}
         GROUP BY action ORDER BY cnt DESC LIMIT 20
    """), {"wid": str(worker_id)})).mappings().all()
    top_errors = (await db.execute(_sql_text(f"""
        SELECT SUBSTRING(error_msg, 1, 120) AS err, COUNT(*) AS cnt
          FROM worker_invocation_log
         WHERE worker_agent_id = :wid AND status='failed' AND error_msg IS NOT NULL
           {window_sql}
         GROUP BY err ORDER BY cnt DESC LIMIT 10
    """), {"wid": str(worker_id)})).mappings().all()
    return {
        "worker_id": str(worker_id),
        "window": window,
        "overall": _jrow(overall),
        "per_action": [_jrow(r) for r in per_action],
        "top_errors": [_jrow(r) for r in top_errors],
    }


@router.get("/api/workers/{worker_id}/overrides")
async def worker_overrides(worker_id: uuid.UUID, db: DBSession, _u: CurrentUser) -> list[dict]:
    """各 super 的 per-super override 列表（workflow_config.worker_overrides[<worker_id>]）。"""
    # workflow_config 是 JSON (非 JSONB)；? 操作符仅支持 jsonb，需要 cast。
    rows = (await db.execute(_sql_text("""
        SELECT p.id AS mission_id, p.slug, p.name, p.supervisor_agent_id,
               (p.workflow_config::jsonb -> 'worker_overrides' -> :wid_text) AS override
          FROM missions p
         WHERE (p.workflow_config::jsonb -> 'worker_overrides') ? :wid_text
    """), {"wid_text": str(worker_id)})).mappings().all()
    return [
        {
            "mission_id": str(r["mission_id"]),
            "slug": r["slug"],
            "name": r["name"],
            "supervisor_agent_id": str(r["supervisor_agent_id"]),
            "override": r["override"],
        }
        for r in rows
    ]


@router.get("/api/workers/{worker_id}/artifacts")
async def worker_artifacts(
    worker_id: uuid.UUID,
    db: DBSession,
    _u: CurrentUser,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    media_type: str | None = None,
) -> dict:
    """该 worker **跨所有 super** 的历史交付聚合。

    交付实物在 `messages.meta`（artifact_url + worker_agent_id），按 worker 维度跨 project 扫，
    带上是哪个 super/mission 产的（修：worker 观察页「交付物聚合」此前是占位 stub，不显示内容）。
    """
    params: dict[str, Any] = {"wid": str(worker_id), "limit": limit, "off": (page - 1) * limit}
    where_extra = ""
    if media_type:
        where_extra = " AND m.meta->>'media_type' = :media_type"
        params["media_type"] = media_type
    rows = (await db.execute(_sql_text(f"""
        SELECT m.id AS message_id, m.created_at,
               m.meta->>'artifact_url' AS artifact_url,
               m.meta->>'media_type' AS media_type,
               m.meta->>'action' AS action,
               m.meta->'artifact_meta' AS artifact_meta,
               p.slug AS super_slug, p.name AS super_name
          FROM messages m
          JOIN missions p ON p.id = m.mission_id
         WHERE m.meta->>'worker_agent_id' = :wid
           AND m.meta ? 'artifact_url'
           {where_extra}
         ORDER BY m.created_at DESC
         LIMIT :limit OFFSET :off
    """), params)).mappings().all()
    return {
        "page": page,
        "limit": limit,
        "items": [
            {
                "message_id": str(r["message_id"]),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "artifact_url": r["artifact_url"],
                "media_type": r["media_type"],
                "action": r["action"],
                "artifact_meta": r["artifact_meta"],
                "super_slug": r["super_slug"],
                "super_name": r["super_name"],
            }
            for r in rows
        ],
    }
