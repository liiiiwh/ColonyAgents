---
date: 2026-05-17
role: dev
task: M1 — Project 生命周期 + Daemon 基座（runtime_status / project_run_state / daemon service / lifecycle API + admin UI 按钮）
related_task_id: M1
files_changed:
  - backend/app/models/project.py             # + runtime_status / ProjectRunState 表
  - backend/app/schemas/project.py            # + ProjectRuntimeStatus / ProjectLifecycleAction / ProjectRuntimePublic
  - backend/app/services/project_daemon.py    # 新建：start/stop/restart/get_runtime/run_once stub/clear_memory stub + 心跳 sweeper + reconcile_on_boot + shutdown_all
  - backend/app/api/projects.py               # + POST /api/projects/{id}/lifecycle/{action}, GET /api/projects/{id}/runtime
  - backend/app/main.py                       # lifespan 内调 reconcile + start_heartbeat_sweeper / shutdown_all
  - backend/app/db/base_all.py                # 注册 ProjectRunState 到 metadata
  - backend/alembic/versions/020_project_lifecycle.py  # 新建迁移
  - frontend/types/project.ts                 # + ProjectRuntimeStatus / ProjectLifecycleAction / ProjectRuntimePublic
  - frontend/lib/api/projects.ts              # + lifecycle / runtime
  - frontend/app/admin/projects/[id]/page.tsx # + RuntimeSection（status 徽章 + Start/Stop/Restart 按钮 + 心跳/启动时间/run_count 展示）
  - backend/tests/test_lifecycle.py           # 新增 5 个测试
status: done
---

## 任务背景

按计划 M1：把 Project 从「元数据」升级为「可启停的运行体」。

## 计划修改范围

**后端**：
- `backend/app/models/project.py`：新增 `runtime_status` enum 列（stopped/starting/running/stopping/error）
- `backend/app/models/project.py`：新表 `ProjectRunState`（id / project_id / status / started_at / last_heartbeat_at / last_error / current_step）
- `backend/app/schemas/project.py`：新增 `ProjectRuntimeStatus` Literal + `ProjectRuntimePublic`
- `backend/app/services/project_daemon.py`（新建）：start / stop / restart / get_status / clear_memory（M3 之前先做 best-effort）/ run_once（M2 用，先 stub）；内部用 `asyncio.create_task` + asyncio.Lock 守护并发；心跳协程每 30s 写 PG
- `backend/app/api/projects.py`：新增 `POST /api/projects/{id}/lifecycle/{action}`（action ∈ start/stop/restart）+ `GET /api/projects/{id}/runtime`
- `backend/app/main.py` 启动期 reconcile：扫库 → 把陈旧 `running` 状态（无 heartbeat > 2 min）改成 `error`
- `backend/alembic/versions/020_project_lifecycle.py`

**前端**：
- `frontend/types/project.ts`：补 ProjectRuntimeStatus + ProjectRuntimePublic
- `frontend/lib/api/projects.ts`：lifecycle / runtime 调用
- `frontend/app/admin/projects/[id]/page.tsx`：顶部加「运行状态」徽章 + start/stop/restart 按钮

## 测试目标

- `pytest` 全部通过（含 sessions/projects）
- 新增 `tests/test_lifecycle.py` 覆盖 start → running → stop 状态机
- `npx tsc --noEmit` 0 错误
- e2e probe：admin 用 API 触发 start → 查 runtime → stop

## 实施步骤记录

1. ORM：`Project.runtime_status` (String(16), 默认 'stopped', 索引) + 新表 `ProjectRunState`（一对一）。
2. Schema：`ProjectRuntimeStatus` Literal + `ProjectLifecycleAction` + `ProjectRuntimePublic`。
3. Service `project_daemon`：
   - 简化设计：不在 start() 里 spawn 长跑协程（避免 ORM 跨 session 并发 race）；只设状态。
   - 全局心跳 sweeper 协程：周期 30s 给所有 `_DAEMONS` 中的 project bump heartbeat；在 lifespan 启动期 spawn，shutdown 取消。
   - `reconcile_on_boot`：扫描 status ∈ {running/starting/stopping} 但心跳 > 120s 没动的，标 error。
   - 模块级 `_open_session` lookup `app.db.session.AsyncSessionLocal` 时机延迟到调用时，让 tests 的 monkeypatch 生效。
4. API：`POST /api/projects/{id}/lifecycle/{action}`（start/stop/restart）+ `GET .../runtime`。
5. Alembic 020：add `projects.runtime_status` + index；新建 `project_run_state` 表。
6. Frontend：types / api 客户端 / 在 admin/projects/[id] 顶部加 `RuntimeSection`（含 Badge / Start/Stop/Restart/Refresh 4 个按钮 / heartbeat & started_at & run_count 详情）。
7. 顺手修：`Badge` 没有 `destructive` variant，error 用 `warning` 染色 + 错误文字单独渲染。

## 验证结果

- ✅ `uv run python -c "from app.main import app"` 成功，109 个路由
- ✅ `alembic upgrade head` 到 020 在远程 PG 上 OK（19 → 20）
- ✅ `uv run pytest -q`：**107 passed, 2 skipped, 0 failed**（含新增 5 个 lifecycle 测试）
- ✅ `npx tsc --noEmit` 0 错误
- ✅ E2E（直连 9022 远程 PG）：
  - POST `/lifecycle/start` → status=running, started_at + heartbeat 同步写入
  - 再次 start → idempotent，状态字段不变
  - GET `/api/projects/{id}` → `runtime_status=running` 同步
  - `/lifecycle/restart` → status=running, new started_at + stopped_at
  - `/lifecycle/stop` → status=stopped, stopped_at 写入
  - DELETE project + DELETE agent 都 204

## 已知遗留 / 后续

- `run_once` / `clear_memory` 都是 stub，M2 / M3 才真正实现。
- 心跳 sweeper 在生产部署多实例时会重复 bump（无害但浪费），M2 升级 scheduler 时一并处理。

## 状态: 可测试 ✅
