"""CapabilityIndex · v6.

worker_capability_actions 表的写入 + 查询 API。

写入：rebuild_for_worker(worker_agent_id) —— 从 agent.extra_config.capability_contract
重建该 worker 的所有 action 行（先 DELETE 后 INSERT）。

查询：find_workers(action?, exclude_side_effects?, requires_approval?, parallel_safe?,
                    idempotent?) → [{worker_agent_id, capability, action, ...}]
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import bindparam, text as _sql_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def rebuild_for_worker(db: AsyncSession, *, worker_agent_id: uuid.UUID) -> int:
    """从 agent.extra_config.capability_contract 重建该 worker 的所有 action 行。

    幂等：先 DELETE 所有该 worker 的行，再 INSERT 新行。
    返回插入数量。

    PG-only（用 INSERT ... CAST(:json AS jsonb)）。
    """
    from app.models.agent import Agent

    agent = await db.get(Agent, worker_agent_id)
    if agent is None or agent.kind != "worker":
        return 0
    contract = (agent.extra_config or {}).get("capability_contract") or {}
    capability = (agent.capability or contract.get("capability") or "")
    advertises = contract.get("advertises") or []

    await db.execute(
        _sql_text("DELETE FROM worker_capability_actions WHERE worker_agent_id = :wid"),
        {"wid": str(worker_agent_id)},
    )

    inserted = 0
    import json as _json
    for spec in advertises:
        if not isinstance(spec, dict):
            continue
        action = spec.get("action")
        if not action:
            continue
        side_effects = spec.get("side_effects") or []
        input_schema = spec.get("input_schema")
        output_schema = spec.get("output_schema")
        await db.execute(_sql_text("""
            INSERT INTO worker_capability_actions
              (worker_agent_id, capability, action, requires_approval, parallel_safe,
               idempotent, side_effects, concurrency_hint, rate_limit,
               input_schema, output_schema, since)
            VALUES (:wid, :cap, :act, :ra, :ps, :idemp,
                    CAST(:se AS jsonb), :ch, :rl,
                    CAST(:is AS jsonb), CAST(:os AS jsonb), :since)
        """), {
            "wid": str(worker_agent_id),
            "cap": capability,
            "act": str(action),
            "ra": bool(spec.get("requires_approval", False)),
            "ps": bool(spec.get("parallel_safe", True)),
            "idemp": bool(spec.get("idempotent", True)),
            "se": _json.dumps(side_effects),
            "ch": spec.get("concurrency_hint"),
            "rl": spec.get("rate_limit"),
            "is": _json.dumps(input_schema) if input_schema is not None else None,
            "os": _json.dumps(output_schema) if output_schema is not None else None,
            "since": spec.get("since"),
        })
        inserted += 1
    await db.commit()
    return inserted


async def find_workers(
    db: AsyncSession,
    *,
    action: str | None = None,
    capability: str | None = None,
    requires_approval: bool | None = None,
    parallel_safe: bool | None = None,
    exclude_side_effects: list[str] | None = None,
    limit: int = 50,
) -> list[dict]:
    """复合查询 worker_capability_actions。

    返回 list of dict，每个 dict = {worker_agent_id, worker_name, capability, action, ...}
    """
    where = ["w.is_enabled = true"]
    params: dict[str, Any] = {"limit": limit}
    if action:
        where.append("a.action = :act")
        params["act"] = action
    if capability:
        where.append("a.capability = :cap")
        params["cap"] = capability
    if requires_approval is not None:
        where.append("a.requires_approval = :ra")
        params["ra"] = requires_approval
    if parallel_safe is not None:
        where.append("a.parallel_safe = :ps")
        params["ps"] = parallel_safe
    if exclude_side_effects:
        # NOT ?| any-of(exclude_side_effects)
        where.append("NOT (a.side_effects @> CAST(:ese AS jsonb))")
        import json as _json
        # 至少含一个 → 用最小包含规则反向；这里简化用 array equality 失效，
        # 改为 element-wise NOT EXISTS：避免假阳性
        # 简化版本：仅当包含**任一**给定 tag 即排除
        where[-1] = (
            "NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(a.side_effects) e "
            "WHERE e = ANY(:ese))"
        )
        params["ese"] = list(exclude_side_effects)
    sql = f"""
        SELECT a.worker_agent_id, w.name AS worker_name, a.capability, a.action,
               a.requires_approval, a.parallel_safe, a.idempotent,
               a.side_effects, a.concurrency_hint, a.rate_limit
          FROM worker_capability_actions a
          JOIN agents w ON w.id = a.worker_agent_id
         WHERE {' AND '.join(where)}
         ORDER BY a.capability, a.action
         LIMIT :limit
    """
    rows = (await db.execute(_sql_text(sql), params)).mappings().all()
    return [
        {
            "worker_agent_id": str(r["worker_agent_id"]),
            "worker_name": r["worker_name"],
            "capability": r["capability"],
            "action": r["action"],
            "requires_approval": r["requires_approval"],
            "parallel_safe": r["parallel_safe"],
            "idempotent": r["idempotent"],
            "side_effects": r["side_effects"],
            "concurrency_hint": r["concurrency_hint"],
            "rate_limit": r["rate_limit"],
        }
        for r in rows
    ]
