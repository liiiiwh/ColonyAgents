# ADR-027 · 标准化到 capability dispatch，退役 mission_nodes / 节点版派发 / by-node workspace

**Status**: Accepted (2026-06-29)
**Builds on / revises**: ADR-018（mission-only：sessions/branches 退役）、ADR-009（Builder 治理：required_capabilities / capability_contract）、ADR-013（Builder 确定性收尾 build_finalizer）、ADR-007（Activity backbone 物理删除）

## Context

平台同时养着**两套 super→worker 派发模型**：

1. **capability 版**（`invoke_worker(capability:slug | agent_id)` / `invoke_workers_parallel` / `list_workers`）：按能力解析**全平台** worker，不依赖 mission 预绑；缺能力 → `request_new_capability` → super 自动 `paused_waiting_capability` → Builder DESIGN_WORKER 建/升级 worker → `resume_super_agent` 唤醒。这套是 `CONTEXT.md`「ATA 闭环关键 verb」里的规范动词。
2. **节点版**（`dispatch_to_worker(node_name)` / `parallel_dispatch`）：按 `mission_nodes.node_name` 查本 mission 预绑的 worker；worker 必须先 `mission_add_node` 挂载。`mission_nodes` 还兼当 super 的"花名册"（`agent_service` 把节点渲成 Markdown 表注入 super 上下文）与 **workspace 状态键**（`workspace[node_name].status/state/artifacts`：进度条、质量门 `qgate_invocations`、decision、交付物追踪）。

节点版是历史遗留（M2 工厂管线的产物），它在 `CONTEXT.md` 词汇表里**没有词条**。两套并存造成：
- **Builder 必须记得 `mission_add_node`**——漏调就建出 0 节点的半成品（mission-df779b 事故：6 worker 建了没挂，节点版 super 抓瞎）。
- 重复的浅 seam（两套 dispatch、两套并发派发），违反"轻量简单"。
- workspace-by-node 把进度/质量/交付物状态耦死在"节点"这个遗留概念上。

事实核查（2026-06-29 运行库）：`mission_nodes` **0 行**——没有任何 mission 实际用节点；`sessions`/`session_branches`/`agent_activities` 已不存在（ADR-018 step5 / ADR-007 已落）；唯一遗留表是 `mission_nodes`。前端右栏（实时 worker 调用 / 线程 / 调度 / 记忆）**无按节点的 Workspace 面板**，进度看 live worker 调用流、交付物内联对话（ArtifactPreview）——前端早是 capability/invocation 取向。本仓库是单 orphan commit 预发布快照，无外部用户/迁移史 → 可干净硬删。

## Decision

### D1 · capability dispatch 为唯一规范，节点版派发退役
- 保留 `invoke_worker` / `invoke_workers_parallel` / `list_workers` / `request_new_capability` 为 super→worker 的唯一派发面。
- **删除** `dispatch_to_worker` / `parallel_dispatch`（节点版）及其 registry / skill_scope 条目。

### D2 · super 花名册 = `extra_config.required_capabilities`（声明在协议/spec，不在 mission_nodes）
- super 需要哪些能力，声明在 `Agent.extra_config.required_capabilities`（已存在，AgentSpec.capabilities 落库；治理层 capability_consumers 已在读）。
- 运行时按能力解析（`invoke_worker capability:x`）+ `list_workers` 发现；缺则 `request_new_capability`。super 不再靠"读 mission_nodes 花名册"。

### D3 · 彻底退役 mission_nodes 与 by-node workspace
- **drop `mission_nodes` 表**（alembic migration）+ 删 `MissionNode` 模型 / schemas / `mission_service` 节点 CRUD / `mission_add_node` skill / `agent_service` 节点花名册渲染。
- worker 产出/状态只活在：**worker thread**（`messages.thread_key='worker:{super}:{worker}'`）+ **worker_invocation_log** + **S3 artifacts**。super 读最近 invocation / worker thread 拿上下文。
- 进度 = live worker 调用流（SSE）；交付物 = 内联对话 ArtifactPreview（均已是现状，不依赖 by-node）。

### D4 · 审核（质量门）= super 编排的能力，删死代码 quality_gate
- 审核走 super 协议编排（调一个审核 worker capability，如内容真实性/去AI化）+ `request_approval`（force_human 人审）。
- **删除** `quality_skills.py` 的 quality_gate 自动插节点机制（已无人调用 = 死代码）+ by-node 的 `qgate_invocations` 计数。重试上界由 tick 级 `max_iterations` / 审批门兜底，不再要 per-node 计数。

### D5 · Builder build 期不再挂节点，默认 super 协议改 capability 版
- `mission_create` 自动建 super 的默认 `protocol_md`：从「`mission_get` 读 worker nodes → `dispatch_to_worker`」改为「按 `required_capabilities` 用 `invoke_worker(capability:x)`；缺能力 `request_new_capability`」。
- Builder `protocol_md` 去掉 `mission_add_node` 构建步骤；`build_finalizer` 找本 mission 相关 MCP 改走「super 绑定的 MCP」而非「mission_nodes agents 绑定的 MCP」。

### D6 · 删 M2 工厂残留
- 删 `factory_meta_skills.py`（clone_project 等 fork 项目 meta 工具）——M2 工厂管线僵尸，与 capability 模型无关。

## Considered alternatives

- **只换默认 dispatch 原语、mission_nodes 全保留**：最小改动但两套 dispatch 仍并存，没清理遗留，违反"轻量简单"。被否。
- **workspace 改按 capability 当 key（保留 workspace-by-X 结构）**：同一 capability 被多步复用会撞 key，且 mission_nodes 表半留不干净；进度/交付物现状已不靠 by-node，没必要保结构。被否。
- **保留 mission_nodes 作为"可选工作流图"**：增加一个不被 dispatch 使用的并行声明层，正是当前遗留的根源；0 行使用证明它不被需要。被否。

## Consequences
- mission 的"工作流/排序/并发"从声明式节点图变为 super 协议(LLM 编排)驱动——更轻、自愈（缺能力自动找 Builder），但不再有确定性 node-order 执行（符合 super=LLM 编排者的定位）。
- 一次性硬删（0 行使用 + 预发布快照），无需数据迁移兼容窗口。
