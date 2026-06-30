# 2026-05-25 · v6 deepening (ATA backbone)

围绕"ATA 全自动 + Builder 自动创建 agent + Agent 工作可视化/可观测/可交互"做架构 deepening。

## 落地清单（按推荐 7 步顺序）

### F · CONTEXT.md + app/domain/ 地基
- 新建 `/Users/wenhuali/www/colony/CONTEXT.md`（≤30 个 domain term，禁漂移）
- 新建 `backend/app/domain/{activity,builder}/` 目录骨架
- 后续 v6 模块全部住这里

### I · Activity (任务树) first-class 数据模型
- migration `044_v6_activities` · `agent_activities` 表（树形：parent_id / kind / status / payload / result / cost_tokens）
- 新 model `app/domain/activity/model.py` (AgentActivity)
- 新模块 `app/domain/activity/recorder.py` (ActivityRecorder · start/finish/fetch_tree/fetch_recent_roots/delete)
- 5 个单元 tracer 测试覆盖（test_v6_activity.py）
- 接入：
  - `super_dispatch_skills._invoke_worker_inner`：所有 6 个 return 路径都 close activity
  - `project_daemon.run_once`：开 tick Activity root + 传 activity_id 给 invoke_worker
- 新 endpoint `GET /api/super/{slug}/activities`（含/不含 root_id 两路）

### A · AgentSpec + Factory
- `app/domain/builder/agent_spec.py` (AgentSpec / SuperSpec / WorkerSpec · pydantic + slug 校验)
- `app/domain/builder/factory.py` (apply_super_spec / apply_worker_spec · 事务化 upsert)
- 新 Builder skill `build_super` / `build_worker` （替代 Builder LLM 5-6 步链）
- 7 个单元 tracer 测试覆盖（test_v6_agent_spec.py）

### B · CapabilityIndex（关系型 worker action 索引）
- migration `045_v6_capability_index` · `worker_capability_actions` 表
- 新模块 `app/domain/builder/capability_index.py` (rebuild_for_worker / find_workers)
- 新 Builder skill `find_workers` （按 action/side_effects/requires_approval/parallel_safe 复合查询）
- 启动 seed 自动 rebuild 所有 catalog worker；apply_worker_spec 也自动 rebuild
- 实测：`find_workers(action='publish_note')` → 1 hit（xhs_ops.publish_note + concurrency_hint）

### J · ActivityTree 前端组件
- 新组件 `frontend/components/activity/ActivityTree.tsx`
- 新 API client `frontend/lib/api/activities.ts`
- 装载到 `/super/[slug]` 右栏「实时」tab 顶部

### K · Intervene Hub
- 新 endpoint `POST /api/activities/{id}/intervene`
- 8 个 verb: approve / reject / interrupt / inject_hint / rewind_to / force_retry / skip / mark_stuck
- 前端 ActivityTree 节点 hover 显示 ⋯ 菜单 → Intervene

### C · Platform 共享 KB + promote
- migration `046_v6_kb_scope` · `knowledge_bases.scope` 字段
- `knowledge_service.get_or_create_platform_kb` + 启动 seed 单例
- 新 skill `promote_to_platform` / `platform_knowledge_search`（所有 super / Builder 可调）

### D · worker_telemetry skill
- 新 Builder skill `worker_telemetry` — 直接拉 worker_invocation_log 聚合
- 返回 success_rate / p95_ms / per_action / top_errors
- Builder 改 worker 协议时调

## 测试
- `pytest tests/test_v5_event_bus.py tests/test_v6_activity.py tests/test_v6_agent_spec.py` 共 **19 passed**
- 端到端：backend + frontend 启动正常；`/api/super/builder/activities` / `/api/activities/{id}/intervene` / capability_index find_workers 三路 smoke 通过

## 数据库迁移
```
044_v6_activities                  · agent_activities 表
045_v6_capability_index            · worker_capability_actions 表
046_v6_kb_scope                    · knowledge_bases.scope 字段
```

## 新 / 改文件清单
- 新：CONTEXT.md / app/domain/{activity,builder}/ / 3 个 migration / 6 个 skill 文件
- 改：super_dispatch_skills.py (Activity 接入) / project_daemon.py (tick activity root) / super_conversation.py (新 endpoint) / models/knowledge.py (scope) / db/init_db.py (platform KB seed) / db/seed_worker_catalog.py (capability_index rebuild) / __init__.py / registry.py
- 前端：lib/api/activities.ts / components/activity/ActivityTree.tsx / app/super/[slug]/page.tsx (mount)
