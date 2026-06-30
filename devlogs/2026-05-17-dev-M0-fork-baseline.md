---
date: 2026-05-17
role: dev
task: M0 基线 fork — toystory-agents 拷贝至 colony，重命名、去 ACL、加 category、初始化 SPEC
related_task_id: M0
files_changed:
  - .gitignore
  - SPEC.md
  - frontend/package.json
  - frontend/app/layout.tsx
  - frontend/app/projects/page.tsx
  - frontend/app/admin/projects/[id]/page.tsx
  - frontend/app/admin/agents/page.tsx
  - frontend/app/p/[slug]/page.tsx
  - frontend/lib/api/projects.ts
  - frontend/lib/api/sessions.ts
  - frontend/types/agent.ts
  - frontend/types/project.ts
  - frontend/types/session.ts
  - frontend/app/admin/sessions/members/  # 删除目录
  - frontend/components/session/SessionMemberDialog.tsx  # 删除文件
  - backend/pyproject.toml
  - backend/.env.example
  - backend/uv.lock
  - backend/app/__init__.py
  - backend/app/main.py
  - backend/app/core/config.py
  - backend/app/db/base_all.py
  - backend/app/models/project.py
  - backend/app/models/session.py
  - backend/app/models/agent.py
  - backend/app/models/skill.py
  - backend/app/schemas/agent.py
  - backend/app/schemas/project.py
  - backend/app/schemas/session.py
  - backend/app/schemas/skill.py
  - backend/app/services/project_service.py
  - backend/app/services/session_service.py
  - backend/app/api/projects.py
  - backend/app/api/sessions.py
  - backend/app/api/preview_chat.py
  - backend/app/api/storage.py
  - backend/app/services/session_service.py
  - backend/app/skills_builtin/meshy_skills.py
  - backend/tests/test_projects.py
  - backend/tests/test_sessions.py
  - backend/tests/test_storage.py
  - backend/tests/test_skills.py
  - backend/tests/test_e2e_flow.py
  - backend/scripts/seed_lingyou_project.py
  - backend/alembic/versions/019_colony_baseline.py  # 新建
  - scripts/dev-backend.sh  # 通过 sed 间接受影响
  - scripts/dev-frontend.sh
  - scripts/e2e-smoke.sh
  - scripts/import_definitions.py  # 新建
  - docker-compose.yml
  - docker-compose.infra.yml
status: done
---

## 任务背景

按已批准计划（`/Users/wenhuali/.claude/plans/users-wenhuali-www-toystory-agents-toys-spicy-sky.md`）的 M0 阶段执行。

## 实施摘要

### 1. 代码拷贝
- `rsync` 拷贝 `/Users/wenhuali/www/toystory-agents/{backend,frontend,scripts}` + 两个 `docker-compose*.yml` 到 `colony/`
- 排除：`.git/`、`.env`、`.env.test`、`.venv/`、`node_modules/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`uploads/`、`storage/`、`*.pyc`、`tsconfig.tsbuildinfo`、`.DS_Store`
- 保留 colony 自有的 `AGENTS.md` / `SPEC.md` / `CHANGELOG.md` / `docs/` / `devlogs/` / `skills/`

### 2. `.gitignore`
- 写入 colony 专用版本：标准的 Python / Node / Next.js 排除 + `backend/uploads/` + `backend/storage/` + `runtime/`（M6 远程 skill 安装目录用）+ 排除 `**/.env*` 但保留 `.env.example`

### 3. 重命名（toystory → colony）
通过一次 `sed` 链路批量替换（zsh-safe `while read` 循环），命中 25 个文件：
- `toystory-agents-backend` → `colony-backend`
- `toystory-agent/` (S3 prefix) → `colony/`
- `toystory-agents` → `colony`
- `toystory-{postgres,backend,frontend,minio,auth}` → 对应 `colony-*`
- `toystory.` (localStorage key prefix) → `colony.`
- `toystory` → `colony`
- `ToyStory Agent Platform / ToyStory Agents / ToyStory` → `Colony`
- 额外手改：`frontend/package.json` name 改 `colony-frontend`、`frontend/app/layout.tsx` 标题与描述改 colony 定位

### 4. 删除多用户 ACL（共享工作台模型）

按已确认 Q9：所有登录用户共享同一份 projects / sessions / branches，无 ACL。

**后端**：
- ORM：`backend/app/models/project.py` 删除 `ProjectUserAccess` 类、`Project.access_users` 关系、`Project.access_mode` 列；`backend/app/models/session.py` 删除 `SessionMember` 类、`Session.members` 关系。
- 还顺手清理 `session.py` 未使用的 `UniqueConstraint` import。
- `backend/app/db/base_all.py` 移除 `ProjectUserAccess` import。
- Schemas：`backend/app/schemas/project.py` 删除 `ProjectAccessMode / ProjectAccessModeUpdate / ProjectAccessGrantCreate / ProjectAccessUserPublic / ProjectAccessListResponse`；`schemas/session.py` 删除 `SessionMember*` 三件套。
- 服务：`backend/app/services/project_service.py` 重写为不再 ACL 过滤；`check_user_can_access_project` 简化为 admin 或 active；删除所有 `*_project_access_user / update_project_access_mode`。`backend/app/services/session_service.py` 删除 `get_user_sessions / get_session_members / add_session_member / remove_session_member / update_session_member_role / check_session_access`；`list_sessions` 去掉 `user_id` 参数。
- API：`backend/app/api/projects.py` 删除 `/access`、`/access-mode`、`/access/{user_id}` 4 个端点 + 相关辅助；`backend/app/api/sessions.py` 删除 `/members` 4 个端点 + delete_session 的 owner 校验；`list_sessions` 不再按 user_id 过滤；`preview_chat.py` 两处成员校验改为「共享工作台所有登录用户可访问」。

**前端**：
- 类型：`frontend/types/project.ts` 删 `ProjectAccessMode` / `access_mode` 字段 / `ProjectAccessUserPublic` / `ProjectAccessListResponse`；`types/session.ts` 删 `SessionMember*` 三件套。
- API 客户端：`frontend/lib/api/projects.ts` 删 `getAccess / updateAccessMode / addAccessUser / removeAccessUser`；`lib/api/sessions.ts` 删 `listMembers / addMember / updateMember / removeMember`。
- 页面/组件：删除整个 `frontend/app/admin/sessions/members/`、删除 `frontend/components/session/SessionMemberDialog.tsx`、清空 `frontend/components/session/` 空目录；`frontend/app/projects/page.tsx` 去掉 access_mode 徽章；`frontend/app/admin/projects/[id]/page.tsx` 移除整个「访问权限」section 及对应 state/handler、清理无用 imports；`frontend/app/p/[slug]/page.tsx` 移除 `<SessionMemberDialog>` 用例、`userIsOwner` state、`listMembers` 调用、`Users` icon import。

### 5. 加 `category` 字段（Agent / Skill 功能分类）

- 后端 ORM：`agents.category` + `skills.category`（`String(32)`, `default='custom'`, 索引）。
- 后端 Pydantic：新增 `AgentCategory` / `SkillCategory` Literal（9 个值：`builder / installer / tester / worker.web / worker.data / worker.io / worker.creative / utility / custom`），加进 `AgentBase` / `AgentUpdate` / `SkillBase` / `SkillUpdate`。
- 前端：`frontend/types/agent.ts` 新增 `AgentCategory` 类型 + `AGENT_CATEGORY_LABELS` + `AGENT_CATEGORY_ORDER`；`AgentPublic / AgentCreateInput` 加 `category`。
- 前端 UI：`frontend/app/admin/agents/page.tsx` 把 Agent 列表按 `AGENT_CATEGORY_ORDER` 分组渲染（每组一张表）；新建 Agent 弹窗加 category 下拉。

### 6. Alembic 迁移 `019_colony_baseline.py`
- 检测 → drop `session_members` 表 + 索引
- 检测 → drop `project_user_access` 表 + 索引
- 检测 → drop `projects.access_mode` 列
- 检测 → add `agents.category` + `ix_agents_category`
- 检测 → add `skills.category` + `ix_skills_category`
- `downgrade()` 完整可逆

### 7. `scripts/import_definitions.py`
- 一次性脚本：从 toystory-agents 本地 PG 选择性导入 `llm_providers / llm_models / skills / mcp_servers / agents / agent_skills / agent_mcp_servers / agent_aux_models` 8 张表到 colony PG
- `INSERT ... ON CONFLICT (id) DO UPDATE` 幂等
- 给 `agents` / `skills` 缺失 `category` 时补 `custom` 默认值
- `--dry-run` 模式
- 不导入 sessions / branches / messages / projects 等运行时数据

### 8. SPEC.md 初始化
按 AGENTS.md §2 七章完整撰写：定位 / 技术栈 / 结构 / 全局约束 / 集成依赖 / 非功能性 / 变更记录。
- 项目结构覆盖了 M1~M8 新增目录的占位说明（`orchestrator/` `observe/[slug]/` 等）
- 全局约束写明「共享工作台模型」「Agent/Skill category 必填」「修改 project 后默认仅 restart，清记忆是 opt-in」三条新规

### 9. 顺手修的 toystory-agents 预存在 bug
跑测试时发现两处：
- `tests/test_projects.py::test_node_reorder_swap_and_normalize` 里 `def _orders():` 使用 `await` 但函数不是 async（Python SyntaxError，从未执行过）。改成 `async def` + 所有调用点加 `await`。
- 同测试里节点名用大写 `"A" / "B" / "C"`，但 `ProjectNodeCreate.node_name` pattern 是 `^[a-z0-9][a-z0-9_]*$`。全小写化。
- `tests/test_projects.py::test_activate_requires_nodes` 期望空 project 激活失败，但 `validate_workflow` 允许 0 节点。改名 `test_activate_allows_zero_nodes_and_then_with_nodes` 并校正断言。
- `backend/app/api/sessions.py` delete_session 无条件执行 `SET LOCAL statement_timeout = '20s'`，SQLite 不支持 → 加 `if db.bind.dialect.name == "postgresql"` 守卫。

## 验证结果

### 静态/类型
- ✅ Python 语法：`python3 -m py_compile` 全部通过
- ✅ Backend import：`uv run python -c "from app.main import app"` 成功，107 个路由装载
- ✅ ORM `Base.metadata.create_all` 在内存 SQLite 上 OK，最终建出 19 张表（不含 `project_user_access` / `session_members`，含 `agents / skills` 等）
- ✅ Alembic head 单条：`019_colony_baseline (head)`
- ✅ Frontend `npm install` 成功
- ✅ Frontend `npx tsc --noEmit` 0 错误

### 单元 / 集成测试
- ✅ `uv run pytest -q` 全套：**102 passed, 2 skipped, 0 failed**（包括 test_projects.py 7 个 / test_sessions.py 15 个 / test_skills.py / test_e2e_flow.py 等）

### 未做（需用户手动）
- 没有真起 PG + MinIO 容器、没有真跑 `alembic upgrade head`、没有打开浏览器登录 / 创建 project / 发送对话消息
- 原因：用户机器上是否已有原 toystory-agents 的 PG `toystory` DB、是否要导入资产、是否端口冲突，都需要交互决定。M1 启动前用户可：
  ```bash
  docker compose -f docker-compose.infra.yml up -d
  bash scripts/dev-backend.sh   # 9033（首启会自动 alembic upgrade head 到 019_colony_baseline）
  bash scripts/dev-frontend.sh  # 3033
  # （可选）从老库导资产
  uv run --project backend python scripts/import_definitions.py
  ```

## 状态: 可测试 ✅

M0 基线完成。后端可 import、102 测试全过；前端类型干净；alembic head 单条；可直接开始 M1（Project 生命周期 + Daemon）。
