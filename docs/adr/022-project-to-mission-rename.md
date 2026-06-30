# ADR-022 · Project→Mission 全量改名（持久层 + 代码 + API + 前端）

- **状态**: Accepted（2026-06-22，grill 定稿）
- **分支**: `main`
- **相关**: ADR-018（mission-only，运行时收口）、ADR-021（后端布局重组）

## 背景

ADR-018 把运行时/域语言收口到 **Mission**，但**持久层与大量代码仍叫 `project`**——这是迁移前的遗留命名（最初的玩具叫 "project"）：

- 模型 `Project`/`ProjectNode`/…，表 `projects`/`project_*`（共 8 张含 `project_approval_channels`/`project_agent_memory_revisions`）。
- FK 列 `project_id`（5 张 project 子表）、`super_project_id`（worker_invocation_log / super_pending_messages）。
- 服务文件 `project_service.py` / `project_daemon.py` / `project_test_runner.py` + 内部函数 `get_project` / `create_project` / `resolve_project_id` …。
- 公开 API `/api/projects`（17 端点，id-based）与较新的 `/api/missions`（3 端点，slug-based）并存。
- 前端 `projectsApi` / `project_id` / `projectId`。

代码库已是「半改名」态：`messages` 等表早用 `mission_id`→`projects.id`，而 project 子表仍用 `project_id`。命名割裂，可读性差，也是 ADR-021 session 清理后剩下的最后一块迁移期命名。

v1 未发布、部署库可弃（docker 重建 / 云端测试库已授权可覆盖）→ **无需向后兼容**。

## 决策

把 `project` 全量改名到 `mission`，分片执行、每片全套测试绿后提交（零行为变更）。

**Slice A（已落地，本 ADR 同提交）— 后端数据层 + 代码：**
- 模型/类：`Project`→`Mission` 及 `ProjectNode/RunState/Schedule/AgentMemory/Escalation/ApprovalChannel…` 全部 `Mission*`；schemas 同改。
- 文件：`models/project.py`→`models/mission.py`、`schemas/project.py`→`schemas/mission.py`、`services/project_{service,daemon,test_runner}.py`→`mission_*`。
- 列：`project_id`→`mission_id`（5 子表）、`super_project_id`→`super_mission_id`（2 表）。
- 表（迁移 073）：`projects`/`project_run_state`/`project_schedule`/`project_agent_memory`/`project_nodes`/`project_escalations`/`project_agent_memory_revisions`/`project_approval_channels` → `mission*`。
- 内部函数：`get_project`/`create_project`/`resolve_project_id`/… → `*_mission*`。
- raw SQL 表名同步；`/api/projects` 路由前缀**暂留**（与既有 `/api/missions` router 冲突，见未决）。
- Alembic `073_project_to_mission_rename`：纯 `ALTER TABLE … RENAME`，幂等（`IF EXISTS`），可逆。

**Slice B（已落地）— LLM 工具 slug：** 审计 13 个 `project_*` 工具 slug 均仍在用（无可删），全部改名 `mission_*`（含 `fork_project_to_workspace`/`sandbox_clone_project`）：registry key + metadata + factory 函数名 + 种子 protocol_md 引用。96 工具零含 project。

**Slice C（已落地）— API 合并 + 前端：**
- `api/projects.py`→`api/missions_admin.py`，prefix `/api/projects`→`/api/missions`；3 个与既有 `/api/missions`(slug-based) 冲突的根路由迁移：`GET ""`→`/all`、`POST ""`→`/full`、`GET /{id}`→`/detail/{id}`；两 router 共存（admin-first include 序，literal 优先于 `/{slug}`）。
- `schedules.py` / `pending_approvals.py` / `clawbot_accounts.py` 路由前缀 `/projects`→`/missions`。
- 前端 `lib/api/*`（projects/schedules/approvals/clawhub/superConversation/observeV3）URL + JSON 字段 `project_id`→`mission_id`、`super_project_id`→`super_mission_id`；tsc 通过。
- UI 实测仅用 5 个操作（list/delete/lifecycle + missionsApi list/create/get）；其余 admin 端点保留（test 覆盖）。

**未决：** 纯结构残留（前端页面路由 `/projects` landing、`projectsApi`/`ProjectPublic` TS 标识符）属内部命名，未改；docker e2e 验证迁移 073 + 工具 slug 重命名后的 LLM 行为。

## 后果
- 正面：持久层 + 代码命名与 Mission 域彻底统一；文件树/查询/模型一眼可读。
- 代价：跨 ~10 表 schema 迁移 + 887 处 `project_id` 改名，churn 极大；靠分片 + 513 全套测试兜底。迁移 073 为纯 rename，尚未对真实 Postgres 跑过（单测走 create_all）。
- 不可逆点：表/列改名（破坏旧 `/api` 之外的 schema 契约）——故立此 ADR。
