---
date: 2026-05-17
role: dev
task: M2 — Scheduler (APScheduler in-process + project_schedule + CRUD API + admin schedules tab)
related_task_id: M2
files_changed:
  - backend/pyproject.toml + uv.lock          # + apscheduler / croniter / tzlocal
  - backend/app/models/project.py             # + ProjectSchedule 表
  - backend/app/schemas/schedule.py           # 新建：ScheduleKind / Create / Update / Public + _validate_expr
  - backend/app/services/scheduler_service.py # 新建：AsyncIOScheduler + rehydrate_from_db + reschedule_one/delete_one/fire_one + lifespan start/stop
  - backend/app/api/schedules.py              # 新建：CRUD + manual fire + webhook fire
  - backend/app/main.py                       # 挂 schedules router + lifespan 调 scheduler_service.start/stop
  - backend/app/db/base_all.py                # 注册 ProjectSchedule
  - backend/alembic/versions/021_project_schedule.py
  - frontend/types/schedule.ts                # 新建
  - frontend/lib/api/schedules.ts             # 新建
  - frontend/app/admin/projects/[id]/page.tsx # + SchedulesSection + NewScheduleDialog
  - backend/tests/test_schedules.py           # 新增 5 个测试
status: done

## 验证结果

- ✅ alembic 021 升级 OK
- ✅ backend import：115 routes（+ 7 = list/create/update/delete/fire + events/{name} + lifecycle 已有）
- ✅ pytest 全套 112 passed, 2 skipped（+5 schedule tests）
- ✅ frontend tsc 0 错
- ✅ e2e probe（远程 PG）：
  - boot 日志显示 `[scheduler] AsyncIOScheduler started` + `rehydrated 0 jobs from DB`
  - `POST /schedules` cron `* * * * *` → next_fire_at 计算正确（下一分钟整）
  - `POST /schedules` 非法 cron → 400 with detail
  - `POST /schedules/{id}/fire` → 触发 run_once，fire_count 与 runtime.run_count 都 +1
  - 删除 schedule / stop project / delete project / delete agent 全 204

## 已知遗留

- APScheduler 内存 jobstore：进程重启时靠 `rehydrate_from_db()` 重建；多 worker 部署会重复触发（M2 范围之外）
- run_once 仍是 stub（M3/M4 真正接 agent 执行）

## 状态: 可测试 ✅
---

## 任务背景

按计划 M2：给 Project 加 cron / interval / event 触发能力。

## 选型

- **APScheduler 3.11.x** + `AsyncIOExecutor` + 内存 jobstore（MVP 单进程；后续可换 Arq / Temporal）
- 不使用 SQLAlchemyJobStore：那个 jobstore 用 pickle 序列化 job 对象，跨重启反序列化容易爆；
  改成「DB 表 `project_schedule` 是 source of truth，启动期 + 每次变更后从 DB rehydrate 到 in-memory APScheduler」的模式。
- 触发到达后，scheduler 调 `project_daemon.run_once(project_id, payload)`。

## 计划修改范围

后端：
- `backend/app/models/project.py` + ProjectSchedule 表（id / project_id / kind: cron/interval/event / expr / payload_template JSONB / enabled / last_fired_at / next_fire_at / created_by / timestamps）
- `backend/app/schemas/schedule.py` 新建 schemas
- `backend/app/services/scheduler_service.py` 新建：start/stop/reschedule_all/upsert_schedule/delete_schedule + APScheduler 实例
- `backend/app/api/schedules.py` 新建：CRUD + manual trigger
- `backend/app/main.py` lifespan：start scheduler / shutdown scheduler
- `backend/alembic/versions/021_project_schedule.py`

前端：
- `frontend/types/schedule.ts` 新建
- `frontend/lib/api/schedules.ts` 新建
- `frontend/app/admin/projects/[id]/page.tsx` 加「Schedules」子区块

测试：
- `backend/tests/test_schedules.py` CRUD + enable/disable + 手动触发
