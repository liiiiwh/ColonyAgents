---
date: 2026-05-17
role: dev
task: M4 — Orchestrator backend + Builder Project seed + /orchestrator page
related_task_id: M4
files_changed:
  - backend/app/models/session.py             # + Session.scope
  - backend/app/schemas/session.py            # + SessionScope literal + SessionPublic.scope
  - backend/app/services/session_service.py   # create_session 接 scope='orchestrator' 参数
  - backend/app/services/stream_service.py    # stream_chat_reply + acting_user_id；ctx.extra 携带
  - backend/app/api/sessions.py               # 调 stream_chat_reply 时透传 user.id
  - backend/app/api/orchestrator.py           # 新建：GET /api/orchestrator/projects, /projects/{id}/session
  - backend/app/main.py                       # 挂 orchestrator router
  - backend/app/skills_builtin/context.py     # memory_scope（在 M3 阶段加）
  - backend/app/skills_builtin/builder_skills.py  # 新建：8 个 Builder 工具
  - backend/app/skills_builtin/__init__.py    # 注册 8 个 builder 工具到 BUILTIN_TOOL_REGISTRY
  - backend/app/skills_builtin/registry.py    # + 8 条 BUILTIN_SKILL_METADATA（category='builder'）
  - backend/app/db/init_db.py                 # + seed_builder_project + 同步 skill.category
  - backend/alembic/versions/023_session_scope.py
  - frontend/lib/api/orchestrator.ts          # 新建
  - frontend/app/orchestrator/page.tsx        # 新建：Builder chat 页 + 目标 project 切换器
  - frontend/app/projects/page.tsx            # + Builder Chat 链接
  - backend/tests/test_skills.py + test_e2e_flow.py  # 适配新增 8 个 builtin skill
status: done

## 验证

- ✅ alembic 023 升级 OK
- ✅ pytest 全套 116 passed
- ✅ 启动期日志：「✅ Builder Project 已就绪 (id=..., slug=builder)」
- ✅ `GET /api/orchestrator/projects` 返回 Builder Project
- ✅ `GET /api/orchestrator/projects/{builder_id}/session` 自动创建 session（scope=orchestrator）
- ✅ frontend tsc 0 错
- ✅ /orchestrator HTTP 200

## 已知遗留

- M4 没有真正测试 Builder AI 调 builder tools（要 LLM 真跑；M7 端到端时一起测）
- 目标 project_id 现在靠用户手动复制 / 在 prompt 里说；未来在 M5/M6 接 SessionState 持久化 + 自动注入
- 顶部"模型选择器"是 placeholder（M4 范围内只展示当前 Builder Supervisor 的 model；切换待 M6/M7 拆分到 UI 设置面板）

## 状态: 可测试 ✅
---

## 任务背景

按计划 M4：把 toystory-agents 的 session/branch/approval/SSE 包装成"Orchestrator"语义；
新增 Builder Project 实体（self-bootstrap）—— 用户通过对话让 Builder AI 创建/修改其他 project；
建立 `/orchestrator` 页面。

## 拆分

- **M4a**：sessions 表加 `scope` 字段（orchestrator / observation_legacy）；新 API namespace `/api/orchestrator/*`
- **M4b**：seed Builder Project + BuilderAgent + InstallerAgent + TesterAgent + builder_skills.py（先做 project/agent/lifecycle CRUD 工具，clawhub/test 等放 M6/M7）
- **M4c**：前端 `/orchestrator/page.tsx`（用 Builder Project 会话 + 模型选择器 + 顶部目标 project 切换器）

## M4a 后端改造

- `backend/app/models/session.py`：`Session.scope: str = "orchestrator"` (default)
- `backend/app/schemas/session.py`：`SessionScope = Literal["orchestrator", "observation_legacy"]`
- `backend/app/api/orchestrator.py`（新建）：薄层 router 直接调 sessions service
  - GET `/api/orchestrator/projects` — list_accessible_projects（已有）
  - GET `/api/orchestrator/projects/{id}/session` — 取/建该 project 的 orchestrator session（单条；与 toystory 多 session 不同）
  - 其他 chat / branch / messages / rollback 继续走 `/api/sessions/*`（已实现）
- `backend/alembic/versions/023_session_scope.py`

## M4b Builder Project seed

挪 alembic seed 比较脆，改成 `app/db/init_db.py` 的 `seed_builder_project` 模块函数：
- 检查是否存在 slug='builder' 的 Project；不存在则用 admin id 创建：
  - 一个 supervisor Agent（name='Builder Supervisor'）category='builder'
  - 三类子 Agent：BuilderAgent (worker.creative)、InstallerAgent (installer)、TesterAgent (tester)
  - ProjectNode 3 条
- 把 `app/skills_builtin/builder_skills.py` 的工具注册到 BUILTIN_TOOL_REGISTRY；只先实现 project_create / project_update / agent_create / project_lifecycle_control / clear_memory；其它（schedule、clawhub、run_test）放 M5+

## M4c 前端

- `frontend/app/orchestrator/page.tsx`：复用 `<ChatArea>`，传入 builder project's slug
- 顶部 model selector（覆盖 Agent.model_id 的运行时 override）→ 通过 chat request 的 extra_meta 透传（M4 先简单：直接 override BuilderAgent.model_id，下次刷新生效）
- 项目切换器：列出非 builder 的所有 project（拿来作为 target_project_id 注入 chat 上下文）

注意：完整 Builder dispatch 流程 (parallel_dispatch + clawhub install) 要等 M6 才能跑端到端；M4 只把 chat UI 跑起来，能让 Builder 调到 project_create / lifecycle 这一层。
