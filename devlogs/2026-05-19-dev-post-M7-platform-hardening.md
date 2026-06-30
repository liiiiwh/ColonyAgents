---
date: 2026-05-19
role: dev
task: M7 之后的平台硬化（异步压缩 / 双轨记忆 / Builder 协议 / Skill 选型 / UI 修复）
related_task_id: post-M7
files_changed:
  - backend/app/db/init_db.py
  - backend/app/core/config.py
  - backend/app/models/project.py
  - backend/app/models/session.py
  - backend/app/schemas/project.py
  - backend/app/services/agent_service.py
  - backend/app/services/session_service.py
  - backend/app/api/sessions.py
  - backend/app/skills_builtin/memory_skills.py
  - backend/app/skills_builtin/builder_skills.py
  - backend/app/skills_builtin/__init__.py
  - backend/app/skills_builtin/registry.py
  - backend/.env
  - backend/.env.example
  - backend/alembic/versions/025_branch_compression_marker.py
  - backend/tests/test_sessions.py
  - backend/tests/test_project_memory.py
  - frontend/components/ui/dialog.tsx
  - frontend/app/admin/agents/page.tsx
  - frontend/app/orchestrator/page.tsx
  - docs/README.md
  - docs/design/architecture.md
  - docs/design/memory-and-context.md
  - docs/design/builder-project.md
  - docs/api/orchestrator.md
  - docs/api/projects.md
  - SPEC.md
status: done
---

## 背景

M7 交付后，在「小红书自动化运营」会话上发现一组体验 / 正确性问题：
- `init_db.py` 上一会话误加的 Project Snapshot Loader Agent 在 admin/agents 显示「未关联到任何项目」
- 自动压缩触发太早（threshold 4000 char）→ Supervisor 几轮就忘
- 压缩摘要太粗（`content[:200]` 占位）+ memory 覆盖式写入 → 多次压缩后旧摘要丢失
- Builder Super 在新 turn 看不到 Worker 已产生的 artifact / state → 反复 dispatch
- Skill 选型一上来就走 ClawHub 装新包，忽略本地 50 个内置 skill
- Builder Chat 看不到 branch v1 标识 → 用户以为分支功能被砍
- 持久化 daemon project 跑久了「忘事」→ Worker 没设计 memory 落地协议

这一批不属于任何单个 Milestone，统一记作「post-M7 platform hardening」。

## 实施清单

### A. 上下文记忆体系重做

| Sub-task | 文件 | 要点 |
|---|---|---|
| 异步压缩 + 不并行 + 水位线 | `services/session_service.py`、`api/sessions.py`、`models/session.py`、`alembic/025` | `schedule_compression_if_needed` 派发 asyncio.Task；进程内 set + DB CAS `compression_in_progress` 双重防并行；完成时写 `compressed_up_to_at` 水位线 |
| 触发判定仅看对话 | `services/session_service.py::_estimate_dialogue_tokens` | system prompt / memory / workspace 不计入阈值，避免「越压越压」恶性循环 |
| 默认阈值 300_000 token | `core/config.py`、`models/project.py`、`schemas/project.py`、`.env*` | 覆盖 1M 窗口的 1/3 安全边界；项目可在 admin/projects/[id] 覆写 |
| LLM 摘要 + 段落隔离 | `services/session_service.py::_llm_summarize` | 输入隔离原则写进 system prompt；每段带 `## 压缩段 #N（起止时间，K 条）` + HTML 注释边界；下次摘要时只看本批消息，不感知前序 segment |
| `memory_append` skill | `skills_builtin/memory_skills.py` | 结构化追加（event / progress / artifacts / decision / next_step / extra）；scope 自动判 branch / project |
| Builder Super 双轨记忆 | `services/agent_service.py::_render_system_prompt` | `memory_scope='branch'` 时同时注入 project memory + branch memory；daemon `memory_scope='project'` 仅注入 project memory |

### B. Builder Project 协议升级

`init_db.py::seed_builder_project` 重写 4 个内置 agent 的 `protocol_md`：

- **Builder Supervisor**：
  - 入口判定（CREATE / EDIT / OPERATE 三种模式）
  - **Skill 选型四级优先级**：builtin → installed → custom → ClawHub（先调 `skill_list_available` 搜本地，没命中才 `clawhub_search`）
  - 落地四步：并行装 skill（仅必要时）→ dispatch BuilderWorker → smoke test → start daemon approval
  - **Memory 自动落地协议**：每完成关键动作（方案选定 / project_create / smoke test / approval 答复）立即 `memory_append`
  - **关键约束**：创建 worker project 时**强制为 worker 设计 memory 协议**（在 worker.protocol_md 末尾加 daemon-mode memory_append 检查点，并把 memory_append + memory_read 绑给 worker）

- **Builder Worker / Installer Agent / Tester Agent**：各自加自己的 memory_append 检查点

- 退役清理：`RETIRED_BUILDER_AGENT_NAMES = {"Project Snapshot Loader"}`，启动期若无引用则自动 delete + 解 AgentSkill

### C. 新 / 改 Skill（在 builder_skills.py）

| Skill | 用途 |
|---|---|
| `skill_list_available` | 搜本地 builtin / installed / custom skill；Builder 选型必走第一步 |
| `project_get` | 读 project 完整结构（supervisor / nodes / 每节点已绑 skill / schedules）；EDIT 模式入口 |
| `schedule_create / schedule_update / schedule_delete` | 让 Builder 直接配 cron / interval / event |
| `memory_append` | 见上 |
| `memory_read` / `memory_write` | 扩展为同时支持 branch + project scope（自动判定） |

绑定结果：Builder Supervisor 24 skills / Builder Worker 14 / Installer 8 / Tester 5。

### D. 上下文组装可见性

`services/agent_service.py::_build_branch_status_snapshot` 扩展，每节点向 Supervisor 暴露：
- 状态徽章（✅ / ⏳ / ⚪️ / ❌）
- artifacts **meta**（label / type / s3_url，**不含 content**——content 不进 prompt 省 token）
- state keys + 单 value ≤ 200 字预览

加守则「优先复述这里的内容，不要再次 dispatch 同一 worker 重新生成」。

### E. 前端修复

| 文件 | 改动 |
|---|---|
| `components/ui/dialog.tsx` | `max-h-[90vh] flex flex-col`，body `min-h-0 flex-1 overflow-y-auto`；解决新建 Agent 弹窗顶出窗口 |
| `app/admin/agents/page.tsx` | 加「按 Category / 按 Project」视图切换；项目维度下显示每个项目用了哪些 agent + 角色（supervisor / node:xxx）+ 未关联到任何项目 兜底组 |
| `app/orchestrator/page.tsx` | 单分支时显示灰色 `branch v1` chip（之前 `branches.length > 1` 才显示 → 用户以为分支功能被砍） |

## 验证

- ✅ AST 检查全部模块通过
- ✅ `uv run pytest -q` → **119 passed, 2 skipped**（修了 1 个旧 assert 因 memory_read 文案改成「尚无 {scope} 记忆」）
- ✅ `from app.main import app` → 125 routes
- ✅ 后端启动正常：alembic 025 已 apply（`compression_in_progress / compressed_up_to_at` 列在 PG 可见）
- ✅ `memory_append` 端到端验证：直接 import + 调用，PG 真库写入 `branch_agent_memories.memory_md` 后 `memory_read` 读出含完整 event/progress/decision/next_step/extra
- ✅ Builder 绑定数：Supervisor 24 / Worker 14 / Installer 8 / Tester 5（含 memory_append）
- ✅ 前端 `tsc --noEmit` 0 错
- ✅ 浏览器预览 `/orchestrator`：「branch v1」chip 渲染在 header 右侧

## Code Review 触发

按 AGENTS.md §1.11，本次改动包含：
- 数据模型变更（`session_branches` 加 2 列）
- 跨模块修改（services / api / skills_builtin / frontend）
- 服务端核心逻辑（异步压缩 / context assembly）

属于 Code Review 触发条件。结论 **pass with risk**：

**Findings & 风险**
- 压缩任务用 in-process `asyncio.create_task`；单 worker 部署没问题，未来多 worker 部署需把 lock 换成 DB advisory lock 或 redis lock。**目前未实施跨进程锁**——但 DB CAS（`WHERE compression_in_progress = FALSE`）已能保证不会有两个 worker 同时跑同一 branch。
- `_estimate_tokens` 用 `len(text)` 估算，中文偏保守、英文偏激进。300_000 默认阈值给了足够安全边界，但若用户跑 1M+ 英文 context 项目可能误触发——可由 project 字段覆写。
- 后台压缩任务异常退出时 `compression_in_progress=False` 由 finally 块清理；若进程 SIGKILL 则 flag 残留——需要人工干预或下次重启时一并 reconcile（**待办**：alembic 026 可加 reconcile，本次暂不做）。
- `memory_append` 在 branch scope 下直接覆写 `existing.memory_md`（避免压缩段 wrapper 套娃），但 `upsert_branch_memory` 公共 API 仍走 segment wrapper——两条路径意图不同已加注释，但调用方需注意。

**建议处理项**：保留为后续 ticket。

## 状态: 可测试 ✅
