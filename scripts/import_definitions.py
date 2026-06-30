#!/usr/bin/env python3
"""从 toystory-agents DB 选择性导入定义型资产到 colony DB。

按计划 Q7（已确认 2026-05-17）：colony 干净起步，但允许把 toystory-agents 已经维护好的
「资产」搬过来重用。本脚本只搬这四张表：

  - providers (LLMProvider)
  - llm_models (LLMModel)
  - agents
  - skills
  - mcp_servers（agent_mcp_servers 关联用得到）
  - agent_skills / agent_mcp_servers / agent_aux_models（Agent 与 Skill / MCP / 辅助模型的绑定）

**不**导入 sessions / branches / messages / projects / project_nodes /
project_user_access / session_members / branch_agent_memories / knowledge_* /
materials 等运行时或业务数据。

使用方式：
    # 默认从 toystory-agents 本地 PG 导到 colony 本地 PG
    uv run python scripts/import_definitions.py

    # 自定义 DSN
    uv run python scripts/import_definitions.py \\
      --src 'postgresql+psycopg://postgres:postgres@localhost:5432/toystory' \\
      --dst 'postgresql+psycopg://postgres:postgres@localhost:5432/colony' \\
      --dry-run

幂等：根据 `id` 做 upsert（PG ON CONFLICT (id) DO UPDATE）。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable

from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

# 要导入的表（顺序很重要：被引用的先建）
TABLES_IN_ORDER: list[str] = [
    "llm_providers",
    "llm_models",
    "skills",
    "mcp_servers",
    "agents",
    "agent_skills",
    "agent_mcp_servers",
    "agent_aux_models",
]

# 不同 toystory-agents 版本的列差异：colony 加了 `category` 字段（默认 'custom'）；
# 源库可能没有这一列，需要 source-side 缺失时用默认值填充。
SOURCE_OPTIONAL_COLUMNS_DEFAULTS: dict[str, dict[str, object]] = {
    "agents": {"category": "custom"},
    "skills": {"category": "custom"},
}


def reflect_table(engine: Engine, name: str) -> Table:
    md = MetaData()
    return Table(name, md, autoload_with=engine)


def fetch_rows(src: Engine, table: Table) -> list[dict]:
    with src.connect() as conn:
        result = conn.execute(table.select())
        return [dict(row._mapping) for row in result]


def upsert_rows(
    dst: Engine,
    table_name: str,
    rows: Iterable[dict],
    extra_defaults: dict[str, object] | None = None,
    *,
    dry_run: bool,
) -> int:
    if not rows:
        return 0
    dst_table = reflect_table(dst, table_name)
    dst_cols = {c.name for c in dst_table.columns}
    count = 0
    with dst.begin() as conn:
        for row in rows:
            payload = {k: v for k, v in row.items() if k in dst_cols}
            # 给 colony 新增字段补默认值（如 category）
            if extra_defaults:
                for k, default in extra_defaults.items():
                    if k in dst_cols and k not in payload:
                        payload[k] = default
            if dry_run:
                count += 1
                continue
            stmt = pg_insert(dst_table).values(**payload)
            # ON CONFLICT (id) DO UPDATE
            update_cols = {
                c.name: getattr(stmt.excluded, c.name)
                for c in dst_table.columns
                if c.name != "id"
            }
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
            conn.execute(stmt)
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Import definition assets toystory-agents → colony")
    parser.add_argument(
        "--src",
        default="postgresql+psycopg://postgres:postgres@localhost:5432/toystory",
        help="源 PG DSN（toystory-agents）",
    )
    parser.add_argument(
        "--dst",
        default="postgresql+psycopg://postgres:postgres@localhost:5432/colony",
        help="目标 PG DSN（colony）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计行数，不写库",
    )
    args = parser.parse_args()

    print(f"源 (toystory-agents): {args.src}")
    print(f"目标 (colony):       {args.dst}")
    print(f"模式: {'dry-run（只读）' if args.dry_run else 'WRITE'}\n")

    src_engine = create_engine(args.src)
    dst_engine = create_engine(args.dst)

    # 验证连通性
    try:
        with src_engine.connect() as c:
            c.execute(reflect_table(src_engine, "agents").select().limit(1))
    except Exception as exc:
        print(f"❌ 无法连接源库或源库没有 agents 表：{exc}", file=sys.stderr)
        return 2
    try:
        with dst_engine.connect() as c:
            c.execute(reflect_table(dst_engine, "agents").select().limit(1))
    except Exception as exc:
        print(
            f"❌ 无法连接目标库或目标库没有 agents 表（请先 `alembic upgrade head`）：{exc}",
            file=sys.stderr,
        )
        return 2

    totals: dict[str, int] = {}
    for table_name in TABLES_IN_ORDER:
        try:
            src_table = reflect_table(src_engine, table_name)
        except Exception as exc:
            print(f"⚠️  跳过 {table_name}（源库没有该表）：{exc}")
            continue
        rows = fetch_rows(src_engine, src_table)
        n = upsert_rows(
            dst_engine,
            table_name,
            rows,
            extra_defaults=SOURCE_OPTIONAL_COLUMNS_DEFAULTS.get(table_name),
            dry_run=args.dry_run,
        )
        totals[table_name] = n
        print(f"  {table_name:20s} → {n} 行")

    print("\n✅ 完成。")
    print("汇总：")
    for k, v in totals.items():
        print(f"  {k:20s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
