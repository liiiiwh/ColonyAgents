# ADR-018 Step 5 · mission-only 终局重构 · 精确执行计划

**Status**: Planned (2026-06-21, 经 grill-with-docs 定稿)
**前置**: B.1 / B.2 / D 核心已完成（见 [adr-018-migration-state 记忆] 与 commit `feb8841`/`81ee671`/`271bec2`）。
**原则**: 绿地最优、零兼容垫片、直接删表删字段（见用户原则「不要无谓的兼容臃肿」）。

## 终态决策（grill 定稿，不再 re-litigate）

1. **thread 解析缝消失**。一个 thread 的身份 = 一个 `thread_key` 字符串，纯函数算出，**没有行要 find-or-create**：
   - `main`（mission 的 daemon 主流，每 mission 一条）
   - `worker:{superId}:{workerId}`（super↔worker 对，两 id 直接拼）
   - `health`（系统自检）
   → 删 `ensure_branch` / `SessionBranch` model / `InvocationContext.resolve_branch` / `_ensure_super_session` / branch_number 单调逻辑。per-(super,worker) 并发锁继续用现有内存 `dict`（`InvocationContext._THREAD_LOCKS`）。
2. **`append_message(db, mission_id, thread_key, role, content, *, meta, token_count, publish)`** —— 调用方传键，零派生、零 branch 垫片。写一条消息 = 1 INSERT，0 派生查询。
3. **`BuiltinToolContext`**：删 `session_id`/`branch_id`，改带 `project_id(=mission_id)` + `thread_key`。工具原来 `get_branch(ctx.branch_id).workspace` → `get_mission(ctx.project_id).workspace`。
4. **workspace → Mission**：`projects` 加 `workspace` JSON + `workspace_version` int 列；`SessionBranch.workspace`/`workspace_version` 退役。`write_artifact`/`write_artifacts_batch`/`compute_progress_map`/`clear` 改操作 `Project`（同 `.workspace`/`.workspace_version` 属性）。S3 key 路径里 `session_id/branch_id` 段简化为 `mission_id/{node}`。
5. **压缩状态 → `thread_compression_state(mission_id, thread_key)` 小表**（`compression_in_progress` CAS + `compressed_up_to_at` 水位线 + `compression_disabled`/`consecutive_failures`/`last_error` 熔断 + thread 级 `compression_config`）。`schedule_compression_if_needed` 的 CAS 改 `UPDATE thread_compression_state ... WHERE mission_id=? AND thread_key=? AND in_progress=false AND disabled=false`。`maybe_compress_context` 按 `(mission_id, thread_key)` 选消息。
6. **记忆**：`ThreadAgentMemory` 成唯一源，删 `BranchAgentMemory` 表 + 双写镜像 `_mirror_thread_memory`（B.1/B.2 的镜像只是过渡）。
7. **`Session` 字段归宿**：`scope` 派生（builder-supervised + is_system，或 Mission 加 `kind` 小字段）；`relay_to_session_id` → message meta 路由（ADR-011 改造）；`target_project_id` → 已有 `built_by_mission_id`；`opened_by`/`status`/`title`/`user_id` 删或并入 Mission。
8. **消息读**：5 处 `Message.branch_id` 读 + `list_messages(branch_id)` → `list_thread_messages(mission_id, thread_key)`（已存在）。drop `messages.session_id`/`branch_id`。
9. **删死代码**：`rollback_to_node`/`activate_branch`/`set_branch_description`（rewind 已 ADR-006 废）、`/api/sessions/*` 的 branch 端点、admin 分支视图、`get_current_branch`/`next_branch_number`。

## 调用面规模（2026-06-21 实测，给新会话估工）

- `append_message` 调用方 **29**；`_ensure_super_session` **6**；`ensure_branch` **2**；`list_messages` **5**。
- 引用 `SessionBranch` 文件 **17**；`from app.models.session import …` 文件 **22**；`.workspace` 读写文件 **10**；压缩 `compression_*` 文件 **2**（session_service + observe_v3）；`BranchAgentMemory` 文件 **16**；`Message.branch_id/session_id` 读 **7**。

## 切片顺序（每片：独立 TDD + 全套绿 + docker 迁移验证 + 提交；云端 drop 永远最后且 gated）

> 先搬「挂在 branch 上的状态」，再动 append/thread/ctx 中枢，最后删表。每片留绿点。

- **Slice W · workspace → Mission**：`projects` 加 `workspace`/`workspace_version`（迁移 + 从 daemon 主 branch 回填）；改写 session_service 四个 workspace 函数操作 Project；10 个消费方 `get_branch(ctx.branch_id)` → `get_mission(ctx.project_id)`。drop 留到 Slice X。
- **Slice K · 压缩状态 → thread_compression_state**：新表 + 迁移回填；CAS/水位线/熔断/thread 级 config 改读新表；`maybe_compress_context` 消息选择按 `(mission_id, thread_key)`。
- **Slice M · 记忆收口**：`ThreadAgentMemory` 设唯一源，删双写镜像 + `get_branch_memory` 回退；记忆 API（`/api/memories`，16 文件面）改 thread 键。
- **Slice H · append/thread/ctx 中枢**（最大）：`thread_key` 纯函数 helper；`append_message(mission_id, thread_key)`；`BuiltinToolContext(project_id, thread_key)`；删 `_ensure_super_session`/`ensure_branch`/`resolve_branch`；29+6+2 调用方改键；5 处消息读 → `list_thread_messages`。
- **Slice S · scope/relay/target 处理**：scope 派生/Mission.kind；relay → message meta；删 `Session.target_project_id` 等。
- **Slice X · 删表删字段删死代码**：drop `sessions` / `session_branches` / `branch_agent_memories` + `messages.session_id/branch_id` + deprecated branch 字段；删 `SessionBranch`/`Session` 模型、`rollback_to_node`/`activate_branch`/`set_branch_description`/branch API 端点/admin 分支视图。**docker 上做完整 drop + e2e 证明，云端等用户显式确认。**

## 执行进度（2026-06-21，branch `adr-018-mission-only`）

- **W done** `741aa05` — 迁移 067。
- **K done** `e63bcec` — 迁移 068；删未用 `domain/compression/compressor.py`。
- **M done** `0d61910` — 迁移 069；删死的 `/api/memories` REST + `frontend/lib/api/memories.ts`。
- **H done** `3dee62d` — 迁移 070（messages.session_id/branch_id 改 nullable）。append_message(mission_id,
  thread_key) 29 调用方全改；BuiltinToolContext 加 thread_key；所有消息读/写、observe_v3/admin_context/
  super_conversation/clear 全切 (mission_id, thread_key)。**H 偏离原计划一点**：seam（`ensure_branch`/
  `resolve_branch`/`_ensure_super_session`/`_get_or_create_super_worker_thread`）**未删**，作为 thread
  注册表 + session 脚手架保留到 X —— 因为删 seam 需要 session 行先消失（scope/relay 迁走 = S），依赖顺序
  要求 seam 删除与 S/X 合并。
- 四片每片 docker scratch DB（宿主 15432）验证迁移 upgrade/downgrade 可逆，**未上云**；全套 522 passed, 2 skipped。

## S 进度（2026-06-21）

- **S·target done** `df032c8` — `Session.target_project_id` 运行时读全部改 `Agent.built_by_mission_id`
  provenance（新 `project_service.get_project_built_by_mission`）：builder 单-super 不变量、build_finalizer、
  escalation fallback（移除）、list_sessions/api/schema/frontend observe 过滤（死参数，删）。列留 X drop。全套 522。
- **S·relay / S·scope 与 X 合并**：实测 relay（session↔session 中继）与 scope（标识 session 容器类型）
  都根植于「session 容器 / builder-chat-as-session」模型，必须等 session→mission 收口（= 删 sessions 表）
  才能真正解耦。它们与 X 一起做：
  - relay_to_session_id：first-run gather 的中继指针，本质 super-mission ↔ builder-chat 中继。mission-only
    下 builder chat = builder mission 的 main thread；中继目标改 mission/thread 指针（或并入 workflow_config）。
  - scope：orchestrator/daemon/observation_legacy 三类 session 容器；mission-only 下由 Mission 性质派生
    （builder 项目 / daemon 运行 / 系统 super），或加 Mission.kind。approval/resolution 按 scope 分支同迁。

## ✅ 全部完成（2026-06-21）— mission-only 终局达成

W/K/M/H/S·target/X1–X5 + 修复 072 全部完成并推送 `adr-018-mission-only`。Session/SessionBranch/
BranchAgentMemory 三表 + 全部 FK 列删除；运行时纯 (mission_id, thread_key)。
- 迁移 067–072（docker fresh DB 001→072 全链验证；含 071 drop 三表 + 072 修 thread_agent_memories.id 类型）。
- **完整 docker e2e（真 PostgreSQL · schema 072）全过**：run_startup_seeds 播种 + 消息往返 + thread 隔离 +
  压缩写 ThreadAgentMemory + 水位线 + 三表确认已删。e2e 抓到并修了 065 的 id=CHAR(32) bug。
- 单测全套 499 passed, 2 skipped（DEBUG true/false 均绿）。
- **云端：063–072 迁移 + 所有 drop 仍 gated，等用户显式确认后执行**（绝不自动碰 182.92.98.228）。

提交链：741aa05(W) e63bcec(K) 0d61910(M) 3dee62d(H) df032c8(S·target) 15e8399(X1) 775aef1(X2)
4441297(X3) dfbf3a0(X4) e81590e(X5) c97593f(072+e2e)。

## X 子阶段（拆除分解，2026-06-21）

- **X1 done** `15e8399` — 删死的 branch/rollback/activate 全套（5 端点 + 2 工具 + registry/工厂/scope + 5 后端函数 +
  2 孤立 helper + 提示词引用 + 6 测试 + e2e rollback 步骤）。无表变更，纯缩面。516 passed。
- **剩余 X2–X5（深度耦合，未做）**，前置测绘已完成（见下「剩余拆除测绘」）：
  - **X2 scope**：删 `Session.scope` 读 —— orchestrator/daemon 容器查询（orchestrator.py:65/133、projects.py:357、
    project_test_runner:222、project_daemon:110）+ approval/resolution.py:44 按 scope 分支 + observe_v3:97。
    由 Mission 性质派生（builder 项目 / daemon 运行 / 系统 super）或加 `Project.kind`。
  - **X2 relay**：`relay_to_session_id`（supervisor_skills:1186 读 + relay_service:60 清 + domain/relay.py + builder_skills:1749 写）
    → mission/thread 指针（builder chat = builder mission 的 main thread）。
  - **X3 FK 迁移**：指向 sessions/session_branches 的外表 —— PendingApproval.session_id/branch_id、
    Agent.proposer_session_id、ProjectEscalation.target_session_id、BuilderOpinionChange/BuilderAttempt.session_id
    → 改指 mission_id 或删列；逐张迁移。
  - **X4 删 session/branch 创建 + 容器读**：`_ensure_super_session`(super_conversation×3/worker_health/daemon/invoke_worker)、
    `_ensure_daemon_session`(builder_skills:1766/build_finalizer)、orchestrator session 创建、`create_session`(api POST)、
    `get_current_branch`(escalation/relay/stream/pending_approval) → 改为直接 (mission_id, thread_key)；
    observe_v3 `/threads` CTE 从 session_branches 重建 → 改纯 thread_compression_state + messages 聚合；
    删 ensure_branch/resolve_branch/_get_or_create_super_worker_thread/list_branches（剩余 seam）。
  - **X5 drop**：迁移 drop sessions/session_branches/branch_agent_memories + messages.session_id/branch_id +
    SessionBranch 压缩列 + Session.target_project_id；删 SessionModel/SessionBranch/BranchAgentMemory 模型 +
    base_all 注册；docker 完整 mission-only e2e；云端 063–070+新迁移 + 所有 drop **gated 用户确认**。

## 剩余拆除测绘（X2–X5 用，2026-06-21 Explore 实测）

- **Session 创建点**：create_session(session_service:63 / api POST:193)、_ensure_super_session(super_dispatch:165)、
  _ensure_daemon_session(project_daemon:100)、orchestrator.py:101/143。
- **Session 字段读**：scope（见 X2）、status(escalation:71/orchestrator:135)、title(observe_v3)、user_id(daemon:123)、
  relay_to_session_id（见 X2）、opened_by(escalation:129)。
- **外表 FK → sessions/session_branches**：messages.session_id/branch_id（已 nullable）、branch_agent_memories.branch_id、
  pending_approvals.session_id+branch_id、agents.proposer_session_id、project_escalations.target_session_id、
  builder_opinion_changes.session_id、builder_attempts.session_id。
- **observe_v3 仍 JOIN session_branches**：`/threads`（sess_main_branch CTE）。其余 artifacts/stats/export 已 mission/thread。
- **测试**：test_compression_thread._mk_thread、test_thread_resolver（ensure_branch）、test_sessions 仍直建 Session/SessionBranch。

## （历史）剩余 S(relay/scope) + X 概述

- **S**：`Session.scope` 派生（Mission.kind 或 builder-supervised+is_system）；`relay_to_session_id`
  → message meta（ADR-011 改造，relay_service/supervisor request_structured_input）；`target_project_id`
  → 已有 `Agent.built_by_mission_id`；`opened_by`/`status`/`title`/`user_id` 删或并入 Mission。目标：运行时
  不再读 Session 任何字段。
- **X**：删 seam（ensure_branch/resolve_branch/_ensure_super_session/_get_or_create_super_worker_thread/
  get_current_branch/next_branch_number/rollback_to_node/activate_branch/set_branch_description）；
  drop `sessions`/`session_branches`/`branch_agent_memories` + `messages.session_id/branch_id` + SessionBranch
  压缩列；删 `SessionModel`/`SessionBranch` 模型、branch API 端点、admin 分支视图、observe_v3 的 branch 重建
  （改纯 mission/thread）；docker 完整 mission-only e2e；云端迁移 063–070 + drop **gated 用户确认**。
- 注意 list_messages（session_service）H 后已无调用方，随 X 删。

## 验证

每片后跑全套单测（当前基线 **521 passed, 2 skipped**）+ 受影响迁移在 docker `colony-fresh` 验证。Slice X 后在 docker 上跑完整 mission-only e2e（创建 super → 派 worker → 审批 → 自动跑 → 压缩 → 召回），证明删表后系统端到端可用。云端迁移 063–066 已验证未上云；本计划的新迁移同样 docker-first、云端 gated。
