# SPEC

> 项目级基础规范。详细 API 文档、设计文档、实现细节请在 `docs/` 维护。
> 本文件遵循 `AGENTS.md §2` 的七章模板。变更必须留版本号与关联 devlog。
>
> ⚠️ **运行时模型已演进到 mission-only（ADR-018/019/020）**：下文部分历史描述（多 session 用户对话面、`api/sessions`、`session_service` 等字样）已退役 —— 现为 `Mission → Message`（`messages.thread_key` 分线程，无 sessions/session_branches 表）。当前权威以 [CONTEXT.md](CONTEXT.md) 术语表 + `docs/adr/018~020` 为准。

---

## 1. 项目定位与背景

**Colony** 是一个「通过对话创建、调度、监控**持久化 Agent 工作流员工**」的平台。

- **使用者**：内部团队多用户共享一份工作台。
- **使用场景**：用户和「Builder Project」对话 → AI 创建/编辑 Project 配置（一组 Agent + 工作流 + Schedule + Skill 绑定）→ 测试通过后**发布**为后台 daemon，按 cron / interval / 事件触发持续执行。
- **核心边界**：
  - Colony 自身**只面向开发与运维**该平台的内部用户，不做对外 SaaS、不做多租户隔离。
  - 单台 Docker Compose 部署即可使用；生产可平滑升级到 K8s + 外部 worker。
  - 通过 https://clawhub.ai/ 自动搜索并安装第三方 Skill；非 Python 类型由 Installer Agent 包装为 Python wrapper 给本平台 Agent 调用。

**历史定位**：从 `toystory-agents`（单次交互式多 Agent 编排）fork 起步，重点改造 = 加 daemon、scheduler、远程 Skill、Builder/Installer/Tester 三类 Meta Agent，去掉多用户 ACL 和多 session 用户对话面。详细路线图见 `~/.claude/plans/users-wenhuali-www-toystory-agents-toys-spicy-sky.md`。

---

## 2. 技术栈与运行环境

### 后端 (`backend/`)
- **语言**：Python 3.12
- **Web 框架**：FastAPI + Uvicorn
- **ORM / 迁移**：SQLAlchemy 2.0 async + Alembic
- **AI/Agent**：LangChain `create_agent` + LangGraph CompiledStateGraph + LiteLLM（多 provider 流式）+ MCP（stdio + http）
- **数据库**：PostgreSQL 15+（含 pgvector）
- **对象存储**：S3 兼容（开发：MinIO / RustFS）
- **包管理**：uv
- **调度**：APScheduler 3.11 in-process AsyncIOScheduler；DB 表 `project_schedule` 是真相，启动期从 DB rehydrate
- **远程 Skill**：clawhub.ai HTTP API（`/api/v1/search` / `/skills/{slug}` / `/download` / `/security`）；按 manifest 自动判 runtime_kind = python / node / nextjs / mcp-server / static-instruction

### 前端 (`frontend/`)
- **框架**：Next.js 14 (App Router) + React 18 + TypeScript
- **样式**：Tailwind CSS
- **状态管理**：Zustand
- **包管理**：npm（保留 toystory-agents 原约定）

### 启动方式
```bash
# 基础设施（PG + MinIO）
docker compose -f docker-compose.infra.yml up -d

# 后端（http://localhost:9022）
bash scripts/dev-backend.sh

# 前端（http://localhost:3022）
bash scripts/dev-frontend.sh
```

### 环境变量
关键变量见 `backend/.env.example`：`DATABASE_URL`（默认指向 `colony` DB）/ `S3_*`（默认 bucket `colony`）/ `JWT_*` / Provider API keys。

---

## 3. 项目结构与模块边界

```
colony/
├── AGENTS.md                 # AI 开发工作流规范（v1.6.0 local）
├── SPEC.md                   # 本文件
├── CHANGELOG.md              # devlogs 归档
├── README.md                 # 待补
├── .gitignore
├── docker-compose.yml        # backend + frontend
├── docker-compose.infra.yml  # PG + MinIO
├── backend/
│   ├── alembic/              # 18 个继承自 toystory-agents + 019_colony_baseline ~ 025_branch_compression_marker
│   ├── app/
│   │   ├── api/              # 13+ REST 路由（auth/health/users/providers/agents/projects/sessions/...）
│   │   ├── models/           # 8 个 ORM 文件
│   │   ├── schemas/          # Pydantic schemas
│   │   ├── services/         # 业务服务（agent_service / session_service / project_service / stream_service ...）
│   │   ├── skills_builtin/   # 内置 Skill 工厂（50 个）+ Builder/Installer/Tester（M4/M6/M7 + v0.10.0 扩充）
│   │   ├── core/             # config / deps / 鉴权
│   │   └── db/               # SQLAlchemy session + base
│   ├── tests/                # pytest
│   ├── scripts/              # 维护脚本（seed / patch）
│   └── pyproject.toml
├── frontend/
│   ├── app/                  # Next.js App Router
│   │   ├── (auth)/login/
│   │   ├── projects/         # 用户落地（active 项目列表）
│   │   ├── p/[slug]/         # M5 起改 redirect → /observe/[slug]
│   │   ├── orchestrator/     # M4 新增：后台 Chat（Builder Project 会话）
│   │   ├── observe/[slug]/   # M5 新增：项目运行观测页
│   │   └── admin/            # 管理后台（providers/agents/projects/users/knowledge/materials/memories/...）
│   ├── components/           # chat/ui/admin/orchestrator 组件层
│   ├── lib/                  # api 客户端 + SSE 处理
│   ├── stores/               # Zustand stores
│   ├── types/                # TS 类型
│   └── package.json
├── scripts/
│   ├── dev-backend.sh
│   ├── dev-frontend.sh
│   ├── e2e-smoke.sh
│   └── import_definitions.py # M0 新增：从 toystory-agents 选择性导入资产
├── docs/                     # 设计/接口/数据模型详档
│   ├── README.md             #   索引
│   ├── design/               #   architecture / memory-and-context / builder-project
│   └── api/                  #   orchestrator / projects
├── devlogs/                  # 开发日志（YYYY-MM-DD-dev-*.md）
│   └── archive/
└── skills/                   # claude-skills 集成（project-standards / code-review）
```

**两层架构（M0 完成后将逐步成型）**：
1. **Meta 层**：`Orchestrator chat（/orchestrator）` — Builder Project + 模型选择器，用户在此创建/修改/测试 Project。
2. **Worker 层**：`Project daemon`（M1）+ `Scheduler`（M2）— 用户「发布」后 daemon 在后台持续运行；用户在 `/observe/[slug]`（M5）只读观测。

**模块职责边界**：
- `app/models/`：仅定义 ORM；不写业务逻辑。
- `app/services/`：业务服务；可调 ORM，不直接处理 HTTP。
- `app/api/`：路由 + Pydantic 验证；只调 services，不直接操作 ORM 复杂查询。
- `app/skills_builtin/`：LangChain BaseTool 工厂；不持有运行时状态。

---

## 4. 全局约束与编码约定

### 后端
- 全异步：FastAPI + SQLAlchemy async（`AsyncSession`）。
- 行注释 / docstring 用中文；变量、函数名英文。
- 错误返回结构：FastAPI HTTPException + `detail` 字符串。
- 不直接 `print`；用 `logging.getLogger(__name__)`。
- Lint：项目根的 `skills/project-standards/SKILL.md` 是权威；现有 ruff 配置生效。
- 测试：pytest + httpx ASGI 测试客户端；优先用真实 PG（容器内）做集成测试。
- **Colony 共享工作台模型**：所有登录用户共享 projects / sessions / branches；不做 user_id 过滤，仅保留 `created_by` 审计。

### 前端
- TypeScript 严格模式。
- 所有跨页面状态用 Zustand store。
- API 请求统一走 `frontend/lib/api/*` 客户端。
- 富文本/Markdown 用 react-markdown + 自带 sanitizer。
- 中文 UI 文案直写；不引入 i18n。

### Agent / Skill 分类约束（M0 引入）
- `agents.category` 与 `skills.category` 字段同枚举：`builder / installer / tester / worker.web / worker.data / worker.io / worker.creative / utility / custom`。
- 管理后台 Agent 列表必须按 category 分组展示。
- 创建 Agent 时必须选择 category（默认 `custom`）。
- Skill 同。

### 项目级生命周期约束（M1 起）
- Project 不再用 `_ACTIVE_TURN_TASKS` 内存 dict 维护运行态；改用 PG 表 `project_run_state` + heartbeat。
- 「修改 Project 后自动行为」：默认仅 restart；用户在 approval 卡片勾选「同时清空记忆」才走 `clear_memory + restart`。

---

## 5. 集成与依赖概览

### 外部基础设施
- **PostgreSQL** + **pgvector**：业务库 `colony`（默认）。
- **S3 兼容存储**：bucket `colony`（默认）；存放 workspace artifacts / memory 压缩快照 / Skill 安装包。
- **MinIO**（开发期）：作为本地 S3。

### LLM Provider
- 通过 LiteLLM 统一适配：Anthropic / OpenAI / DeepSeek / Gemini / Ollama / Azure / 自定义 openai-compat（含 Nebula 代理）。
- 多 Provider 可在管理后台配置；Builder Project 顶部模型选择器默认 `claude-opus-4-7`。

### 远程能力源（M6 起）
- **https://clawhub.ai/**（API base `https://clawhub.ai/api/v1`）：搜索 / 安装第三方 Skill。
- 鉴权 Bearer token（环境变量 `CLAWHUB_TOKEN`，可空走匿名读）。
- 安全前置 `/security` 接口必查；高危 capability 标签触发 approval。

### 调度（M2 起）
- APScheduler 3.x + SQLAlchemyJobStore（PG）。
- 单进程 in-process；后续可替换 Arq / Temporal / Inngest。

---

## 6. 非功能性需求

| 维度 | 目标 |
|------|------|
| **可用性** | 单 Docker Compose 一键起；daemon 容器重启后能 reconcile（M1） |
| **并发** | 单 backend worker；同一 session 串行 chat（已实现）；多 project daemon 并发跑（M1） |
| **延迟** | SSE 首 token < 2s（已实现 keepalive 注释行防 idle 断连） |
| **数据安全** | `.env` 中含敏感 key；不入仓；session token JWT；Bearer 鉴权 |
| **远程 Skill 安装** | 高危 capability 必须 approval；下载前查 security 接口；安装目录隔离在 `runtime/skills/` |
| **可观测** | logs 用 `logging`；M8 之后可考虑 OpenTelemetry |
| **兼容性** | 浏览器主流 evergreen；后端 Python 3.12+；DB PG 15+ |

---

## 7. 变更记录

| 日期 | 版本 | 变更说明 | 关联日志 |
| :--- | :--- | :--- | :--- |
| 2026-05-17 | v0.1.0 | 初始化模板 | — |
| 2026-05-17 | v0.2.0 | M0 基线：从 toystory-agents fork；重命名 colony；去除多用户 ACL；agents/skills 新增 category；alembic 019_colony_baseline | `devlogs/2026-05-17-dev-M0-fork-baseline.md` |
| 2026-05-17 | v0.3.0 | M1 Project lifecycle + Daemon 基座（runtime_status / project_run_state / start/stop/restart/heartbeat sweeper / boot reconcile）；admin UI RuntimeSection | `devlogs/2026-05-17-dev-M1-project-lifecycle.md` |
| 2026-05-17 | v0.4.0 | M2 Scheduler（APScheduler in-process + project_schedule + CRUD + webhook event fire + 内存 rehydrate）；admin UI SchedulesSection | `devlogs/2026-05-17-dev-M2-scheduler.md` |
| 2026-05-17 | v0.5.0 | M3 项目级记忆（project_agent_memory + memory_scope + clear_memory wiring）；RuntimeSection 加 Clear Memory 按钮 | `devlogs/2026-05-17-dev-M3-project-memory.md` |
| 2026-05-17 | v0.6.0 | M4 Orchestrator chat（sessions.scope + /api/orchestrator/* + seed Builder Project + 8 个 builder_skills + /orchestrator 页面） | `devlogs/2026-05-17-dev-M4-orchestrator.md` |
| 2026-05-17 | v0.7.0 | M5 观察页（/observe/[slug] 只读 + 5 按钮 + 5s 轮询；/p/[slug] redirect） | `devlogs/2026-05-17-dev-M5-observation.md` |
| 2026-05-17 | v0.8.0 | M6 ClawHub 集成（HTTP client + 安装器 + runtime kind 检测 + 6 个 clawhub_skills + admin/skills ClawHub Tab） | `devlogs/2026-05-17-dev-M6-clawhub.md` |
| 2026-05-18 | v0.9.0 | M7 AI Smoke Test（project_test_runner + sandbox 克隆 + LLM judge + 3 个 tester_skills；Builder Supervisor & TesterAgent 绑定 project_run_test） | `devlogs/2026-05-18-dev-M7-smoke-test.md` |
| 2026-05-19 | v0.10.0 | **Post-M7 平台硬化**：异步上下文压缩（alembic 025 + `compression_in_progress` + `compressed_up_to_at` 水位线 + 进程内/DB 双重防并行）；阈值 4000 → **300_000** token；触发判定仅看对话本身；`memory_append` skill + Builder Super 双轨记忆注入（branch + project）；Builder 4 个 agent 协议升级（CREATE/EDIT/OPERATE 三模式 + Skill 选型四级优先 + 自动落 memory + 创建 worker 时强制设计 memory 协议）；新增 `skill_list_available / project_get / schedule_create / schedule_update / schedule_delete` 5 个 builder skill；Dialog 弹窗 `max-h-[90vh]`；admin/agents 按 Project 维度分组；orchestrator 单分支也显示 `branch v1` chip；初始化 `docs/` 设计 + API 文档 | `devlogs/2026-05-19-dev-post-M7-platform-hardening.md` |
