# Builder Project

> Colony 自带的 self-bootstrap 项目（`slug='builder'`）。用户与它对话，由它创建 / 编辑 / 启停其他 Super + Worker。
>
> ⚠️ **部分过时（ADR-018 mission-only 之后）**：入口已从 `/orchestrator` 改为 mission 工作台（`/mission/builder`）；"orchestrator session / branch" 退役 —— Builder 对话即 builder mission 的 `main` 线程（`messages.thread_key='main'`），"branch memory" 应读作 "thread memory"。当前权威见 [CONTEXT.md](../../CONTEXT.md) + [ADR-018](../adr/018-mission-only-model-and-iteration-routing.md)。以下保留作历史设计参考。

## 4 个内置 Agent

种子在 `backend/app/db/init_db.py::seed_builder_project`；启动期每次都 force-sync 关键字段（`soul_md / protocol_md / category / produces_deliverable`），代码升级后旧库自动跟上。

| Agent | category | 角色 | produces_deliverable |
|---|---|---|---|
| Builder Supervisor | builder | 编排：拆解用户需求 + 派 worker / installer / tester | ❌（不算交付物源） |
| Builder Worker | builder | 落地：按 Supervisor 给的方案明细做 project_create / agent_create / skill_bind / schedule_create | ✅ |
| Installer Agent | installer | 安装：从 ClawHub 搜 / 装 / 卸 skill | ✅ |
| Tester Agent | tester | 测试：sandbox 复制 project 跑 smoke test + LLM judge | ✅ |

历史退役清单：`RETIRED_BUILDER_AGENT_NAMES = {"Project Snapshot Loader"}`——启动期若 row 存在且无引用则自动清掉。

## Skill 绑定

绑定数和绑定列表来自 `init_db.py` 内的 `builder_skill_slugs` 与各 agent 专属 list。

| Agent | 数量 | 关键 skill |
|---|---|---|
| Builder Supervisor | 24 | request_approval / request_structured_input / dispatch_to_worker / parallel_dispatch / `skill_list_available` / `project_get` / project_create / project_update / project_delete / agent_create / skill_bind / skill_unbind / project_lifecycle_control / project_apply_changes / `schedule_create` / `schedule_update` / `schedule_delete` / clawhub_search / clawhub_inspect / clawhub_list_installed / memory_read / memory_write / `memory_append` / project_run_test |
| Builder Worker | 14 | skill_list_available / project_get / project_create / project_update / agent_create / skill_bind / skill_unbind / schedule_create / schedule_update / schedule_delete / memory_read / memory_write / memory_append / workspace_write |
| Installer Agent | 8 | clawhub_search / clawhub_inspect / clawhub_install / clawhub_uninstall / clawhub_list_installed / request_approval / memory_append / workspace_write |
| Tester Agent | 5 | project_run_test / sandbox_clone_project / sandbox_cleanup / memory_append / workspace_write |

## Builder Supervisor 工作流模式

由 `protocol_md` 强制执行。第一件事：判定**入口模式**——

### CREATE 模式（target_project_id 为空 / 用户说「我要做一个」）

1. **方案候选**：输出 2~3 个不同角度的完整方案，每个含：方案名 / 触发方式 / Agent 链 / 关键 Skill / 产出形态 / trade-off
2. **Skill 选型四级优先**：先 `skill_list_available(query=..., source='builtin')` 找；本地没合适才 `clawhub_search`
3. 用户敲定方案 → `memory_append(event='方案选定', decision=..., next_step='dispatch builder_worker')`
4. **并行装 Skill**（仅当真的需要新装）：`parallel_dispatch([(InstallerAgent, A), (InstallerAgent, B), ...])`
5. **dispatch BuilderWorker** 落配置：传方案明细，Worker 严格按 `project_create → agent_create × N → skill_bind × N → schedule_create → workspace_write` 顺序
6. **smoke test**：直接 `project_run_test(project_id, scenario)` 或 dispatch TesterAgent
7. **start daemon approval**：弹 1 张卡「测试通过，是否启动？☐ 同时清空 project memory」→ 用户批准 → `project_lifecycle_control(action='start')`

### EDIT 模式（target_project_id 存在且非 builder）

1. `project_get(target_project_id)` 拉到当前结构 → 摘要给用户「当前 N 个 Agent + M 个 Skill + 触发：X」
2. 问「想加什么 / 改什么 / 删什么？」
3. dispatch BuilderWorker 做差量改动（agent_create / skill_bind / agent_update）
4. `project_apply_changes(project_id, clear_memory=False)`（默认仅 restart，approval 卡片提供「同时清空记忆」复选框）

### OPERATE 模式（用户说「跑一次 / 停掉 / 重启 / 清记忆」）

直接调 `project_lifecycle_control(action=...)`，无需 dispatch。

## Memory 自动落地协议（关键）

每完成下面任一动作必须立即 `memory_append`：

| 时机 | event | 必带字段 |
|---|---|---|
| 用户敲定方案 | `方案选定: <方案名>` | decision / next_step |
| project_create 成功 | `落地完成: project=<slug>` | progress / extra={project_id} |
| smoke test verdict | `Smoke Test PASS/FAIL` | decision=verdict + 置信度 / artifacts |
| request_approval 答复 | `审批通过 / 拒绝` | decision |
| 工具失败 / 用户改主意 | `方案调整 / xxx 失败` | next_step |

## 创建 Worker Project 时强制设计 Worker Memory 协议

Builder Supervisor 调 `agent_create(protocol_md=...)` 为目标 project 建 worker agent 时，**必须**在生成的 protocol_md 末尾加入：

```markdown
## Memory 落地协议（持久化执行 daemon 强制）
- 我是 daemon 模式运行；每次 turn 启动时已自动注入「项目长期记忆」
- 完成每个有意义动作后立即 `memory_append`：
  - `event`=动词开头
  - `progress`=本次循环进度
  - `artifacts`=本次产物 meta 数组
  - `next_step`=下一步要做什么
- 失败也要 append（event='抓取失败', extra={error_code: ...}）
```

并把 `memory_append` + `memory_read` skill 绑给 worker。

**违反时**：跑久了 worker「忘事」。排错路径：`project_get` → 检查 worker.protocol_md → 没有 memory_append 指令就 `agent_update` 补上 → `project_apply_changes`。

## 危险操作硬约束

由 Builder Supervisor protocol 强制：

- `project_delete` / `clear_memory` / `project_apply_changes(clear_memory=True)` 必须先 `request_approval`
- 高危 ClawHub capability（requires-binary / can-make-purchases / requires-wallet 等）由 InstallerAgent 自己弹 approval；Supervisor 只负责派任务

## 双轨记忆注入

Builder Supervisor 在 orchestrator session 运行（`memory_scope='branch'`）时，`_render_system_prompt` 会同时注入：

- 「项目长期记忆」：Builder Project 自己的 `project_agent_memory`（跨 session 累积学到的事）
- 「当前分支记忆」：当前 orchestrator branch 的 `branch_agent_memory`（本会话累积）

详见 [memory-and-context.md](memory-and-context.md)。

## UI 入口

- `/orchestrator`：Builder Project 会话页（侧栏 session 列表 + 目标 project 切换器 + branch v1 chip + workspace 面板）
- `/admin/agents`：可编辑 4 个 Builder Agent 的 soul_md / protocol_md / category / 绑定 skill —— Builder 越用越好

## 相关代码索引

| 关注点 | 入口 |
|---|---|
| 4 个 Agent seed + 退役清理 | `app/db/init_db.py::seed_builder_project` |
| Builder skill 工具集 | `app/skills_builtin/builder_skills.py` |
| ClawHub 工具集 | `app/skills_builtin/clawhub_skills.py` |
| Tester 工具集 | `app/skills_builtin/tester_skills.py` |
| Memory 工具集 | `app/skills_builtin/memory_skills.py` |
| Orchestrator API | `app/api/orchestrator.py` |
| Orchestrator UI | `frontend/app/orchestrator/page.tsx` |
