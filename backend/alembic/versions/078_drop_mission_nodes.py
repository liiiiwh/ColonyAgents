"""drop mission_nodes table (ADR-027 · 节点版派发退役)

ADR-027 D1/D3 终局：super→worker 派发统一为 capability dispatch（invoke_worker /
invoke_workers_parallel / list_workers）。mission_nodes 表（节点版派发的预绑花名册 +
by-node workspace 状态键）彻底退役。

事实核查（2026-06-29 运行库）：mission_nodes 0 行 —— 没有任何 mission 实际用节点；
单 orphan commit 预发布快照，无外部用户/迁移史 → 干净硬删，不做数据迁移。

- 删表：mission_nodes（CASCADE 连带 FK 约束一并去除）
- mission.workspace JSON 列**保留**（ADR-027 D3：workspace 结构不在本次删除范围；
  quality_gate verdict / 中间态仍按 worker capability label 落 workspace JSON dict，
  与已删的 mission_nodes 行无关联）

Revision ID: 078_drop_mission_nodes
Revises: 077_agent_kind_not_null
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "078_drop_mission_nodes"
down_revision: str | None = "077_agent_kind_not_null"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # CASCADE：连带 PG 的 index + FK 约束一并去除
    op.execute("DROP TABLE IF EXISTS mission_nodes CASCADE")


def downgrade() -> None:
    # ADR-027 终局删除不可逆（节点版派发退役后无 mission_nodes 概念）。
    raise NotImplementedError(
        "ADR-027 D3 删 mission_nodes 为终局操作，不支持 downgrade（capability dispatch 后无节点概念）。"
    )
