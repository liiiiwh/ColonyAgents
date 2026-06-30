"""上下文压缩服务：按 (mission_id, thread_key) 把超阈值的旧对话 LLM 摘要进 ThreadAgentMemory。

消息选择、token 估算、三级配置解析（thread > super > 平台默认）、水位线、CAS 派发锁、
熔断都挂在 thread_compression_state 上；压缩产出的摘要追加进 ThreadAgentMemory（见 memory_service）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy import select, text as _sql_text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import (
    Message,
    ThreadAgentMemory,
    ThreadCompressionState,
)
from app.models.mission import Mission
from app.services.memory_service import get_thread_memory

logger = logging.getLogger(__name__)


async def get_compression_state(
    db: AsyncSession, mission_id: uuid.UUID, thread_key: str
) -> ThreadCompressionState | None:
    return (
        await db.execute(
            select(ThreadCompressionState).where(
                ThreadCompressionState.mission_id == mission_id,
                ThreadCompressionState.thread_key == thread_key,
            )
        )
    ).scalar_one_or_none()


def _estimate_tokens(text: str) -> int:
    """对中英混合 text 的 token 数做保守估计。

    中文场景下 1 char ≈ 1 token；英文略高估。直接用 `len(text)` 作为 upper bound——
    宁可早压一点也不要让 prompt 真的炸掉 LLM context window。
    """
    return len(text or "")


def _estimate_dialogue_tokens(uncompressed_msgs: Sequence[Message]) -> int:
    """估算「未压缩 user↔supervisor 对话」的 token 数。

    **仅看对话本身**——不含 supervisor system prompt（soul/protocol/skills）、
    不含 memory_md、不含 workspace 快照。这三个静态部分各自有自己的体量，
    把它们算进压缩阈值会让 memory_md 越写越长后越来越容易触发压缩，
    形成「越压越压」的恶性循环。

    覆盖：
      - role ∈ {user, assistant} 的 content（dispatch / tool_call 等已过滤）
      - 估算用 len(text)，对中文偏保守
    """
    total = 0
    for m in uncompressed_msgs:
        if m.role not in ("user", "assistant"):
            continue
        total += _estimate_tokens(m.content or "")
    return total


# ── R19/R20/R21 三级压缩配置解析 ──
# 解析顺序：thread (ThreadCompressionState.compression_config) > super (Mission.compression_config
# + Mission.context_compression_threshold) > 平台默认 (system_settings)。
# V28：threshold ≥ 1000；keep_recent ∈ [3, 100]。V29：admin 改 system_settings → invalidate cache。

_COMPRESSION_PLATFORM_CACHE: dict[str, object] = {}
_COMPRESSION_PLATFORM_CACHE_TS: float = 0.0
_COMPRESSION_PLATFORM_CACHE_TTL = 60.0  # 1 分钟；admin 改后通过 invalidate_platform_cache 立即失效


def invalidate_compression_platform_cache() -> None:
    """admin 改 system_settings 后调；下次解析压缩配置会重读 DB。"""
    global _COMPRESSION_PLATFORM_CACHE_TS
    _COMPRESSION_PLATFORM_CACHE.clear()
    _COMPRESSION_PLATFORM_CACHE_TS = 0.0


async def _load_platform_compression_defaults(db: AsyncSession) -> dict[str, object]:
    """读 system_settings 拿三个键的当前值；带 60s 进程缓存。"""
    import time as _t
    global _COMPRESSION_PLATFORM_CACHE_TS
    now = _t.time()
    if _COMPRESSION_PLATFORM_CACHE and now - _COMPRESSION_PLATFORM_CACHE_TS < _COMPRESSION_PLATFORM_CACHE_TTL:
        return dict(_COMPRESSION_PLATFORM_CACHE)
    out: dict[str, object] = {
        "threshold_tokens": 30000,
        "keep_recent": 20,
        "target_ratio": 0.3,
    }
    try:
        rows = (await db.execute(_sql_text(
            "SELECT key, value FROM system_settings WHERE key IN "
            "('compression.threshold_tokens','compression.keep_recent_messages','compression.target_ratio')"
        ))).all()
        for k, v in rows:
            if k == "compression.threshold_tokens":
                out["threshold_tokens"] = int(v)
            elif k == "compression.keep_recent_messages":
                out["keep_recent"] = int(v)
            elif k == "compression.target_ratio":
                out["target_ratio"] = float(v)
    except Exception:
        logger.exception("[compression] system_settings 读失败，沿用代码兜底默认")
    _COMPRESSION_PLATFORM_CACHE.clear()
    _COMPRESSION_PLATFORM_CACHE.update(out)
    _COMPRESSION_PLATFORM_CACHE_TS = now
    return dict(out)


async def resolve_compression_config(
    db: AsyncSession,
    *,
    thread_config: dict | None,
    project: Mission | None,
) -> dict[str, int | float]:
    """合并 thread / super / 平台默认三级；返回 {threshold_tokens, keep_recent, target_ratio}。

    优先级（高 → 低）：
      1. thread_config（thread 级 · ThreadCompressionState.compression_config）
      2. Mission.compression_config + Mission.context_compression_threshold（super 级）
      3. system_settings（平台级，带 60s 进程缓存）
    """
    cfg = await _load_platform_compression_defaults(db)
    if project is not None:
        if getattr(project, "context_compression_threshold", None):
            cfg["threshold_tokens"] = int(project.context_compression_threshold)
        proj_cc = getattr(project, "compression_config", None) or {}
        if isinstance(proj_cc, dict):
            for k in ("threshold_tokens", "keep_recent", "target_ratio"):
                if k in proj_cc and proj_cc[k] is not None:
                    cfg[k] = proj_cc[k]
    if isinstance(thread_config, dict):
        for k in ("threshold_tokens", "keep_recent", "target_ratio"):
            if k in thread_config and thread_config[k] is not None:
                cfg[k] = thread_config[k]
    # V28 上下限
    try:
        cfg["threshold_tokens"] = max(1000, int(cfg["threshold_tokens"]))
    except Exception:
        cfg["threshold_tokens"] = 30000
    try:
        kr = int(cfg["keep_recent"])
        cfg["keep_recent"] = max(3, min(100, kr))
    except Exception:
        cfg["keep_recent"] = 20
    try:
        tr = float(cfg["target_ratio"])
        cfg["target_ratio"] = max(0.05, min(0.95, tr))
    except Exception:
        cfg["target_ratio"] = 0.3
    return cfg


async def maybe_compress_context(
    db: AsyncSession,
    mission_id: uuid.UUID,
    thread_key: str,
    agent_node_name: str,
    threshold_tokens: int | None = None,
    *,
    keep_recent: int | None = None,
) -> ThreadAgentMemory | None:
    """超过阈值时压缩一个 thread（mission_id, thread_key）的旧消息（ADR-018 step5/K）。

    触发条件：**仅 user↔supervisor 对话的估算 token 数** ≥ threshold_tokens。
    System prompt / memory_md / workspace 都不参与判定——它们是给 Supervisor 的
    «侧通道» 知识，不应让其膨胀拖累对话保留范围。

    压缩动作：把除最近 keep_recent 条以外的 user/assistant 消息 LLM 摘要进 ThreadAgentMemory
    （追加式），并把这些消息标 `is_compressed=True`，水位线落到 thread_compression_state。

    R21：threshold_tokens / keep_recent 不传时，按 thread > super > 平台默认 三级解析。
    """
    if threshold_tokens is None or keep_recent is None:
        proj = await db.get(Mission, mission_id)
        state = await get_compression_state(db, mission_id, thread_key)
        thread_cc = state.compression_config if state else None
        cfg = await resolve_compression_config(db, thread_config=thread_cc, project=proj)
        if threshold_tokens is None:
            threshold_tokens = int(cfg["threshold_tokens"])
        if keep_recent is None:
            keep_recent = int(cfg["keep_recent"])
    stmt = (
        select(Message)
        .where(
            Message.mission_id == mission_id,
            Message.thread_key == thread_key,
            Message.is_compressed.is_(False),
        )
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(stmt)
    msgs = list(result.scalars().all())
    if not msgs:
        return None

    # R3-1 · 决策走纯函数 policy（边界逻辑可独立测）
    from app.domain.compression.policy import should_compress, pick_compressible
    total_tokens = _estimate_dialogue_tokens(msgs)
    if not should_compress(total_tokens=total_tokens, threshold_tokens=threshold_tokens):
        return None

    compressible = pick_compressible(msgs, keep_recent=keep_recent)
    if not compressible:
        logger.warning(
            "[maybe_compress_context] dialogue tokens=%d ≥ 阈值=%d 但未压缩消息只有 %d 条 "
            "（< keep_recent=%d），无可压缩对象。建议调高阈值或减少 keep_recent",
            total_tokens, threshold_tokens, len(msgs), keep_recent,
        )
        return None
    logger.info(
        "[maybe_compress_context] 触发压缩：dialogue tokens=%d ≥ 阈值=%d，将压缩 %d 条消息",
        total_tokens, threshold_tokens, len(compressible),
    )

    # 原子事务：memory upsert + messages.is_compressed=True 要么一起成功要么一起回滚
    # 避免"memory 已写但消息未标记"或反之导致下次再压缩时重复
    summary = await _llm_summarize(db, compressible)
    # 段落自包含：携带本段覆盖的消息时间范围 + 数量，未来调试时能溯源
    first_ts = compressible[0].created_at.strftime("%Y-%m-%d %H:%M") if compressible else "?"
    last_ts = compressible[-1].created_at.strftime("%Y-%m-%d %H:%M") if compressible else "?"
    seg_n = len(compressible)
    seg_body = (summary or "").strip()

    def _wrap_segment(seq_no: int, *, leading_separator: bool) -> str:
        # 段落自包含：起止 HTML 注释边界 + 时间范围 + 消息数量
        # 防止下一次 compression 的 LLM 把上一段误当成「之前的对话」
        prefix = "\n\n---\n" if leading_separator else ""
        return (
            f"{prefix}"
            f"## 压缩段 #{seq_no}（{first_ts} ~ {last_ts}，{seg_n} 条消息）\n"
            f"<!-- 该段为独立摘要，覆盖上述时间窗口的对话，不引用其他段落 -->\n\n"
            f"{seg_body}\n\n"
            f"<!-- end 压缩段 #{seq_no} -->"
        )

    try:
        # ThreadAgentMemory upsert：本次摘要包成自包含压缩段追加进 memory_md
        existing = await get_thread_memory(db, mission_id, thread_key, agent_node_name)
        now = datetime.now(UTC)
        if existing:
            prev_count = (existing.memory_md or "").count("## 压缩段 #")
            seq_no = prev_count + 1
            new_total = (existing.compressed_message_count or 0) + len(compressible)
            existing.memory_md = (existing.memory_md or "") + _wrap_segment(
                seq_no, leading_separator=True
            )
            existing.compressed_message_count = new_total
            existing.last_compressed_at = now
            memory = existing
        else:
            memory = ThreadAgentMemory(
                mission_id=mission_id,
                thread_key=thread_key,
                agent_node_name=agent_node_name,
                memory_md=_wrap_segment(1, leading_separator=False),
                compressed_message_count=len(compressible),
                last_compressed_at=now,
            )
            db.add(memory)
        ids = [m.id for m in compressible]
        await db.execute(update(Message).where(Message.id.in_(ids)).values(is_compressed=True))
        # 水位线落 thread_compression_state（单一真相源）：created_at <= watermark 的消息已压缩
        watermark = compressible[-1].created_at
        await _upsert_compression_watermark(db, mission_id, thread_key, watermark)
        await db.commit()
        await db.refresh(memory)
    except Exception:
        await db.rollback()
        logger.exception(
            "maybe_compress_context 事务失败，已回滚 (mission=%s, thread=%s, agent=%s)",
            mission_id, thread_key, agent_node_name,
        )
        return None

    logger.info(
        "🗜️  已压缩 %d 条消息 → memory (mission=%s, thread=%s, agent=%s, size=%d chars)",
        len(compressible), mission_id, thread_key, agent_node_name, len(summary),
    )
    return memory


async def _upsert_compression_watermark(
    db: AsyncSession, mission_id: uuid.UUID, thread_key: str, watermark: datetime
) -> None:
    """更新（必要时创建）thread_compression_state 的水位线（不 commit，由调用方统一提交）。"""
    res = await db.execute(
        update(ThreadCompressionState)
        .where(
            ThreadCompressionState.mission_id == mission_id,
            ThreadCompressionState.thread_key == thread_key,
        )
        .values(compressed_up_to_at=watermark)
    )
    if res.rowcount == 0:
        db.add(ThreadCompressionState(
            mission_id=mission_id, thread_key=thread_key, compressed_up_to_at=watermark,
        ))


# ── 异步压缩派发 ───────────────────────────────────────────────
# 进程内并发保护：避免同一 thread 在同一进程被并行触发两次压缩。
# 真正的跨进程保护靠 ThreadCompressionState.compression_in_progress（DB 标记），
# 配合「set flag 在事务内独立提交」实现 compare-and-swap。
_COMPRESSION_IN_PROGRESS_LOCAL: set[str] = set()
# 持强引用避免 asyncio.create_task 创建的任务被 GC 误回收
_COMPRESSION_BG_TASKS: set = set()


def _thread_lock_key(mission_id: uuid.UUID, thread_key: str) -> str:
    return f"{mission_id}:{thread_key}"


async def _ensure_compression_state_row(
    db: AsyncSession, mission_id: uuid.UUID, thread_key: str
) -> None:
    """保证 (mission_id, thread_key) 有一行 thread_compression_state（幂等，吞并发冲突）。"""
    existing = await get_compression_state(db, mission_id, thread_key)
    if existing is not None:
        return
    try:
        db.add(ThreadCompressionState(mission_id=mission_id, thread_key=thread_key))
        await db.commit()
    except Exception:
        # 并发下别的协程已插入 → 回滚后继续（CAS 会处理后续）
        with suppress(Exception):
            await db.rollback()


async def schedule_compression_if_needed(
    mission_id: uuid.UUID,
    thread_key: str,
    agent_node_name: str,
    threshold_tokens: int | None = None,
    *,
    keep_recent: int | None = None,
) -> bool:
    """异步派发一次 thread（mission_id, thread_key）压缩任务（fire-and-forget · ADR-018 step5/K）。

    本函数本身**很快返回**——不等待压缩完成，请求处理可以继续走完整对话上下文。
    压缩完成后会：
      1. 把对应消息标 `is_compressed=True`
      2. 在 `ThreadAgentMemory.memory_md` 末尾追加新摘要段
      3. 更新 `thread_compression_state.compressed_up_to_at` 水位线
      4. 清掉 `thread_compression_state.compression_in_progress` flag

    并发保护：
      - 进程内已有任务在跑：直接返回 False，**不**重复派发
      - DB 标记 `compression_in_progress=True`：返回 False（兜底）
      - CAS 设置 `compression_in_progress=True`（带 WHERE 条件，避免 race）

    Returns:
        True：成功派发一个后台任务；False：已有任务在跑 / 触发条件不满足
    """
    import asyncio

    lock_key = _thread_lock_key(mission_id, thread_key)
    # 进程内首次拦截（极快路径）
    if lock_key in _COMPRESSION_IN_PROGRESS_LOCAL:
        logger.debug("[schedule_compression] thread=%s 已有压缩任务在跑，跳过", lock_key)
        return False

    # CAS 设置 DB flag（在独立短事务里）。若 DB 已为 True / disabled 都拒绝
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await _ensure_compression_state_row(db, mission_id, thread_key)
        result = await db.execute(
            update(ThreadCompressionState)
            .where(
                ThreadCompressionState.mission_id == mission_id,
                ThreadCompressionState.thread_key == thread_key,
                ThreadCompressionState.compression_in_progress.is_(False),
                ThreadCompressionState.compression_disabled.is_(False),  # C4：disabled 跳过
            )
            .values(compression_in_progress=True)
            .returning(ThreadCompressionState.id)
        )
        got = result.scalar_one_or_none()
        await db.commit()
        if got is None:
            logger.debug(
                "[schedule_compression] thread=%s DB flag CAS 失败 / disabled，跳过", lock_key
            )
            return False

    _COMPRESSION_IN_PROGRESS_LOCAL.add(lock_key)

    async def _runner() -> None:
        had_error = False
        err_text = ""
        try:
            async with AsyncSessionLocal() as db:
                await maybe_compress_context(
                    db, mission_id, thread_key, agent_node_name,
                    threshold_tokens, keep_recent=keep_recent,
                )
        except Exception as exc:  # noqa: BLE001
            had_error = True
            err_text = f"{type(exc).__name__}: {exc}"
            logger.exception("[schedule_compression] background task failed (thread=%s)", lock_key)
        finally:
            _COMPRESSION_IN_PROGRESS_LOCAL.discard(lock_key)
            # C4：失败上报 + 连续失败 3 次后 disabled
            try:
                async with AsyncSessionLocal() as db:
                    state = await get_compression_state(db, mission_id, thread_key)
                    if state is not None:
                        state.compression_in_progress = False
                        if had_error:
                            state.last_compression_error = err_text[:1000]
                            state.compression_consecutive_failures = (
                                (state.compression_consecutive_failures or 0) + 1
                            )
                            if state.compression_consecutive_failures >= 3:
                                state.compression_disabled = True
                                logger.error(
                                    "[schedule_compression] thread=%s 连续 %d 次压缩失败 → disabled；"
                                    "管理员需手动重置 thread_compression_state.compression_disabled=False",
                                    lock_key, state.compression_consecutive_failures,
                                )
                        else:
                            state.last_compression_error = None
                            state.compression_consecutive_failures = 0
                        await db.commit()
            except Exception:
                logger.exception(
                    "[schedule_compression] 清 compression_in_progress flag 失败 (thread=%s)", lock_key
                )

    task = asyncio.create_task(_runner())
    _COMPRESSION_BG_TASKS.add(task)
    # C3：进程内集合在 task 真完成后才清；finally 已 discard，这里再加 callback 兜底
    task.add_done_callback(_COMPRESSION_BG_TASKS.discard)
    task.add_done_callback(lambda _t: _COMPRESSION_IN_PROGRESS_LOCAL.discard(lock_key))
    logger.info("[schedule_compression] 已派发后台压缩任务 (thread=%s)", lock_key)
    return True


# R3-7 · 摘要纯函数已抽到 app/domain/compression/summarizer.py；这里保留 thin re-export
from app.domain.compression.summarizer import (  # noqa: E402
    fallback_summarize as _fallback_summarize,
    build_summarize_payload as _build_summarize_payload,
    SUMMARIZE_SYSTEM_PROMPT as _SUMMARIZE_SYSTEM_PROMPT,
)


async def _llm_summarize(db: AsyncSession, messages: list[Message]) -> str:
    """真实 LLM 摘要。失败回落到 _fallback_summarize（永不丢消息）。"""
    if not messages:
        return ""
    try:
        # R4-1 · 走 service 层 llm_resolver（不再 local-import api/preview_chat）
        from langchain_core.messages import HumanMessage, SystemMessage
        from app.services.llm_resolver import resolve_default_chat_llm

        llm = await resolve_default_chat_llm(db)
        # 这里不要 streaming，要一次性拿到完整摘要
        with suppress(Exception):
            llm.streaming = False  # type: ignore[attr-defined]
        payload = _build_summarize_payload(messages)
        out = await llm.ainvoke([
            SystemMessage(content=_SUMMARIZE_SYSTEM_PROMPT),
            HumanMessage(content=payload),
        ])
        text = getattr(out, "content", None) or str(out)
        if isinstance(text, list):
            # 部分 provider 会返回 [{'type':'text', 'text':...}] 列表
            text = "".join(
                seg.get("text", "") if isinstance(seg, dict) else str(seg)
                for seg in text
            )
        text = (text or "").strip()
        if not text:
            raise RuntimeError("LLM 返回空文本")
        return text
    except Exception:
        logger.warning("_llm_summarize 失败，回落到 fallback 摘要", exc_info=True)
        return _fallback_summarize(messages)
