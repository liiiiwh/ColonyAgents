# Projects / Lifecycle / Schedules API

> Prefix: `/api/projects`
> 所有端点鉴权（Bearer access_token）。Colony 是「共享工作台」，无 user_id 过滤；保留 `created_by` 审计。

## Projects CRUD

| 方法 | 端点 | 用途 |
|---|---|---|
| GET | `/api/projects` | 全量列表 |
| GET | `/api/projects/active` | 仅 status='active'（普通用户落地） |
| GET | `/api/projects/{id}` | 项目详情 + nodes（ProjectDetail） |
| GET | `/api/projects/public/{slug}` | slug 公开访问入口 |
| POST | `/api/projects` | 新建（含 slug 唯一校验） |
| PUT | `/api/projects/{id}` | 更新基础字段 |
| DELETE | `/api/projects/{id}` | 删除 mission（级联 nodes / schedules + 该 mission 的 messages / thread 压缩状态 / thread 记忆；`?cascade_agents=true` 连独占的 super/worker 一起删；系统对象如 Builder 返 409） |
| POST | `/api/projects/{id}/activate` | 切到 active 状态 |
| POST | `/api/projects/{id}/deactivate` | 切到 archived 状态 |

### ProjectCreate 字段

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `name` | ✅ | | ≤128 字符 |
| `slug` | ✅ | | `^[a-z0-9][a-z0-9-]*$`，全局唯一 |
| `description` | | `""` | ≤512 字符 |
| `supervisor_agent_id` | ✅ | | 必须先 agent_create 建好 |
| `auto_approve` | | false | true 时跳过 approval 卡片直接执行 |
| `context_compression_threshold` | | 300_000 | 见 [memory-and-context.md](../design/memory-and-context.md) |

## Project Nodes

| 方法 | 端点 | 用途 |
|---|---|---|
| GET | `/api/projects/{id}/nodes` | 节点列表（按 node_order） |
| POST | `/api/projects/{id}/nodes` | 新增节点 |
| PUT | `/api/projects/{id}/nodes/{node_id}` | 修改节点 |
| DELETE | `/api/projects/{id}/nodes/{node_id}` | 删节点 |

### ProjectNodePublic 字段

```ts
{
  id: string; project_id: string; agent_id: string;
  node_name: string;     // 同 project 内唯一
  node_order: number;
  node_config: Record<string, unknown>;
  parallel_group: string | null;
  agent_name: string | null;
  agent_produces_deliverable: boolean;
  created_at: string;
}
```

## Lifecycle（运行态控制）

| 方法 | 端点 | 用途 |
|---|---|---|
| POST | `/api/projects/{id}/lifecycle/{action}` | action ∈ `start / stop / restart / clear_memory / run_once` |
| GET | `/api/projects/{id}/runtime` | 查 ProjectRuntimePublic（status + 心跳 + 错误） |

### `ProjectRuntimePublic`

```ts
{
  project_id: string;
  status: 'stopped' | 'starting' | 'running' | 'stopping' | 'error';
  started_at: string | null;
  stopped_at: string | null;
  last_heartbeat_at: string | null;
  last_error: string | null;
  current_step: string | null;
  run_count: number;
}
```

### Action 语义

| action | 行为 |
|---|---|
| `start` | 装配 Supervisor + Workers → 起 asyncio task；写 `project_run_state` + 心跳 |
| `stop` | 发取消信号 → graceful shutdown → 更新状态 |
| `restart` | stop → wait idle → start（不清记忆） |
| `clear_memory` | 删 `project_agent_memory` + 关联 s3 key + workspace blob 重置 |
| `run_once` | 单次触发，不写常驻态；用于 sandbox smoke test |

### Heartbeat & Reconcile

- 心跳间隔由 `project_daemon._heartbeat_sweeper_loop` 控制（默认 30s）
- 启动期 reconcile：心跳新鲜的 project 保留 running 状态，超时则标 `error`
- Schedule 在启动期从 `project_schedule` 表 rehydrate 到 APScheduler

## Schedules

> 不同 router 实例但共享前缀。源码 `app/api/schedules.py`。

| 方法 | 端点 | 用途 |
|---|---|---|
| GET | `/api/projects/{id}/schedules` | 该 project 的 schedule 列表 |
| POST | `/api/projects/{id}/schedules` | 新增 schedule |
| PUT | `/api/projects/{id}/schedules/{schedule_id}` | 修改 |
| DELETE | `/api/projects/{id}/schedules/{schedule_id}` | 删除 |
| POST | `/api/projects/{id}/schedules/{schedule_id}/fire` | 手动触发一次（不影响下次自动） |
| POST | `/api/projects/{id}/events/{event_name}` | webhook event fire |

### `ScheduleCreate` 字段

| 字段 | 取值 |
|---|---|
| `name` | 1-128 字符 |
| `kind` | `cron` / `interval` / `event` |
| `expr` | cron 表达式（如 `0 8 * * *`）/ interval 字串（`30s` `5m` `2h` `1d`）/ event 名（`^[a-z0-9][a-z0-9_-]*$`） |
| `payload_template` | 默认 `{}`；触发时合并到 daemon 启动 payload |
| `enabled` | 默认 true |

## Bulk Model Update

`POST /api/projects/{id}/bulk-update-models`

```ts
{ supervisor_model_id?: string; worker_model_id?: string }
```

批量改：supervisor_model_id 覆盖 supervisor agent 的 model_id；worker_model_id 覆盖 project 里所有 worker agent（去重）。返回真实更新的 agent_ids。

## 相关代码索引

| 关注点 | 入口 |
|---|---|
| Projects CRUD | `app/api/projects.py` |
| Schedules CRUD | `app/api/schedules.py` |
| Lifecycle | `app/api/projects.py::lifecycle_control / get_runtime` |
| Daemon 实现 | `app/services/project_daemon.py` |
| Scheduler | `app/services/scheduler_service.py` |
| ORM | `app/models/project.py` |
| Schema | `app/schemas/project.py` / `app/schemas/schedule.py` |
