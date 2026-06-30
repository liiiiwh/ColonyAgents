# Colony 架构总览

> ⚠️ **部分过时（ADR-018 mission-only 之后）**：本文描述的 **Orchestrator / Session / Branch** 两层模型已退役。运行时现为 `Mission → Message`，按 `messages.thread_key` 分线程（无 `sessions` / `session_branches` / `branch_agent_memories` 表，`/orchestrator` UI/API 已删）。当前权威见 [CONTEXT.md](../../CONTEXT.md) 术语表 + [ADR-018](../adr/018-mission-only-model-and-iteration-routing.md) / [ADR-019](../adr/019-onboarding-i18n-and-worker-import.md) / [ADR-020](../adr/020-thread-key-scheme-and-mission-only-cleanup.md)。以下保留作历史设计参考。

## 两层架构

```
┌──────────────────────────────────────────────────────────────────┐
│  Meta 层（Orchestrator）                                          │
│  ─ /orchestrator UI ↔ Builder Project 会话                         │
│  ─ Builder Supervisor 通过对话创建 / 修改 / 启停其他 project       │
│  ─ 保留 session / branch / approval / rollback / SSE 完整能力       │
└─────────────────┬────────────────────────────────────────────────┘
                  │ project_apply_changes / lifecycle_control
                  ▼
┌──────────────────────────────────────────────────────────────────┐
│  Worker 层（持久化 Project Daemon）                                │
│  ─ runtime_status: stopped / starting / running / stopping / error │
│  ─ Scheduler: cron / interval / event webhook 三种触发              │
│  ─ Heartbeat sweeper：探测崩溃 daemon 并标 error                    │
│  ─ Boot reconcile：进程重启后从 DB rehydrate 心跳新鲜的 project     │
└─────────────────┬────────────────────────────────────────────────┘
                  │ 运行日志、产物、事件
                  ▼
┌──────────────────────────────────────────────────────────────────┐
│  观测层（/observe/[slug]）                                         │
│  ─ 只读 SSE：消息流 / Workspace 产物 / 运行历史                     │
│  ─ 5 个轻量按钮：Run once / Pause / Resume / Restart / Clear logs   │
└──────────────────────────────────────────────────────────────────┘
```

## 关键架构决策

### 1. Builder Project 是 Project 而不是另起一套 chat 内核
- **self-bootstrap**：`slug='builder'` 的内置 Project，supervisor + 3 个 worker agent（Builder Worker / Installer / Tester）
- 用户在 `/orchestrator` 触发的会话**本质是 Builder Project 的 orchestrator session**
- 复用现成的 Session / Branch / Supervisor / Worker / SSE / Approval 链路
- 优点：admin 可在 `/admin/agents` 直接编辑 Builder 的 soul_md / protocol_md / 绑定 skill 让 Builder 越用越好

### 2. Worker Project 的真相分布

| 信息 | 真相源 |
|---|---|
| 运行态（running / stopped / error） | `projects.runtime_status` + `project_run_state` 心跳 |
| 编排（哪些 agent / node_order） | `project_nodes` 表 |
| 触发（cron / interval / event） | `project_schedule` 表，启动期 rehydrate 到 APScheduler |
| 长期记忆 | `project_agent_memory` (per project × agent_node_name) |
| 工作区（artifacts / state） | `session_branches.workspace` JSON 列 |
| 安装的远程 Skill | `remote_skill_install` + `skills` mirror row |

进程内**不**持有运行态——`_ACTIVE_TURN_TASKS` 这种 in-memory dict 在 M1 已经替换为 DB 表 + 心跳。

### 3. Skill 来源（优先级硬约束）

由 Builder Supervisor 的协议强制执行：

1. **builtin**（colony 自带 50+ 工具：fetch_url / knowledge_search / workspace_write / memory_* / ...）
2. **installed**（已从 ClawHub 装过的）
3. **custom**（admin 手工建过的 instruction skill）
4. **ClawHub**（仅当前 3 级没合适才走）

由 `skill_list_available` 工具实现「搜本地」入口；Builder Super 必须先调它再考虑 ClawHub。

## 模块边界（backend）

| 目录 | 职责 | 不做的事 |
|---|---|---|
| `app/models/` | ORM 表定义 | 业务逻辑 |
| `app/services/` | 业务服务、SQL 复杂查询、跨表事务 | 直接处理 HTTP |
| `app/api/` | FastAPI 路由 + Pydantic 验证 + 鉴权依赖 | 直接 ORM 复杂查询（要走 service） |
| `app/skills_builtin/` | LangChain BaseTool 工厂 | 持有运行时状态 |
| `app/core/` | config / 鉴权 / FastAPI deps | 业务逻辑 |
| `app/db/` | engine / session / base / seed | — |

## 数据流：用户提交一条消息到 SSE 返回

```
[POST /api/sessions/{id}/chat]
    │
    ├─ schedule_compression_if_needed (异步派发，~10ms 返回)
    │
    ├─ 装配 Supervisor Agent
    │    └─ _render_system_prompt:
    │         soul_md + protocol_md + skill instructions
    │         + memory（branch + project）
    │         + project_nodes_snapshot
    │         + branch_status_snapshot (worker state + artifact meta)
    │
    ├─ 加载 prior_messages (is_compressed=False 的 user/assistant)
    │
    └─ 起 SSE generator → stream_service.stream_chat_reply
         │
         ├─ LangGraph executor 执行
         │    └─ Supervisor 思考 + tool_call
         │         ├─ dispatch_to_worker / parallel_dispatch
         │         │    └─ Worker Agent 跑：fetch_url / workspace_write / 等
         │         ├─ project_create / agent_create / skill_bind 等 Builder 工具
         │         ├─ memory_append（每完成关键动作）
         │         └─ request_approval（弹卡片，等用户）
         │
         └─ 边跑边 yield SSE chunks（assistant token / tool_call event / artifact 通知）
```

## 异步任务

| 任务 | 触发 | 实现 |
|---|---|---|
| 上下文压缩 | 每次 chat 请求开头 | `asyncio.create_task` + DB CAS lock |
| Schedule 触发 | APScheduler | in-process AsyncIOScheduler |
| Heartbeat sweeper | 启动后定时（默认 30s） | `project_daemon._heartbeat_sweeper_loop` |
| Smoke test sandbox | TesterAgent 调 `project_run_test` | clone → run_once → judge → cleanup |

详见各 [memory-and-context.md](memory-and-context.md) / [builder-project.md](builder-project.md)。
