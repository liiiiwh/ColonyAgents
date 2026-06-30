# Colony — Frontend

Next.js 14（App Router）前端，对应后端 FastAPI（仓库根 `../backend`）。默认端口 **3022**，后端默认端口 **9022**。

> 本前端是 [colony](../README.md) 项目的一部分。请优先阅读根 `README.md` 与 `docs/`。

## Stack

- **Next.js 14** · React 18 · TypeScript 5 · App Router
- **Tailwind CSS 3** + 自研 shadcn 风格组件（`components/ui/*`）
- **Zustand**（状态管理，含 persist 中间件）
- **Axios**（统一封装在 `lib/api.ts`，含 Bearer / 401 自动 refresh 拦截器）
- **AI SDK Data Stream Protocol** 客户端消费（`lib/sse.ts`）
- **lucide-react** 图标

## 目录结构

```
frontend/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                # 根路径按角色分流（admin→/admin，user→/projects）
│   ├── (auth)/login/page.tsx   # 登录页
│   ├── projects/page.tsx       # 普通用户 landing（仅 active 项目卡）
│   ├── admin/                  # 全量管理后台（非 admin 进入被踢回 /projects）
│   │   ├── layout.tsx          # AdminLayout + Sidebar
│   │   ├── page.tsx            # Dashboard
│   │   ├── providers/          # LLM Provider CRUD
│   │   ├── agents/             # Agent 列表 + [id] 编辑
│   │   ├── skills/             # Skill 管理
│   │   ├── mcp-servers/        # MCP Server 管理
│   │   ├── projects/           # Project 列表 + [id] 编辑 + 激活；👁 直跳 landing
│   │   ├── knowledge/          # 知识库 + 文档索引 + 检索
│   │   ├── storage/            # 对象存储浏览
│   │   ├── sessions/           # 会话上下文看板（折叠/展开所有消息）
│   │   ├── memories/           # BranchAgentMemory 浏览 + 编辑
│   │   └── users/              # 用户管理（CRUD + role；自我保护 UI）
│   └── p/[slug]/page.tsx       # 终端用户会话（分支 | 聊天 | Workspace 三栏）
├── components/
│   ├── ui/                     # Button / Input / Label / Dialog / Select / Textarea / Badge
│   ├── admin/                  # Sidebar 等后台专用
│   ├── providers/              # Providers 页面子组件
│   ├── chat/                   # ChatArea / MessageList / ToolCallCard / ArtifactCard / ApprovalUI
│   ├── workspace/              # WorkspacePanel / ArtifactRenderer / NodeStatusCard
│   └── workflow/               # NodeEditor（预留）
├── lib/
│   ├── api.ts                  # axios 实例 + 401 refresh 拦截
│   ├── api/                    # 按模块拆分的薄封装（users.ts / agents.ts / projects.ts ...）
│   ├── sse.ts                  # AI SDK Data Stream 解析
│   └── utils.ts
├── stores/
│   ├── authStore.ts            # 用户 + token（持久化到 localStorage）
│   ├── sessionStore.ts
│   └── workspaceStore.ts
├── types/                      # 共享 TS 类型
└── next.config.ts              # /api/* rewrites → BACKEND_URL
```

## 角色与路由守卫

- 未登录访问任意页面 → `/login`（登录成功后按 role 或 `?next=` 返回）
- `admin` 自动跳 `/admin`，可访问全部 `/admin/*`
- `user` 自动跳 `/projects`，只能看 `status=active` 项目；`/admin/*` 会被 AdminLayout 踢回
- `/p/[slug]` 任何登录用户都可访问，但对未激活项目仍返 404

详细权限设计见 [`../docs/api/users.md`](../docs/api/users.md)。

## 开发

需要先把后端跑起来（默认 `http://localhost:9022`）。根目录提供一键脚本：

```bash
# 根目录
bash scripts/dev-backend.sh    # 端口 9022
bash scripts/dev-frontend.sh   # 端口 3022
```

或在 `frontend/` 内：

```bash
npm install
npm run dev      # next dev -p 3022
```

打开 `http://localhost:3022/login`，默认账号 `admin / admin123`（由后端 `.env` 的 `INIT_ADMIN_*` 控制）。

### 环境变量（`frontend/.env.local`）

| 变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `BACKEND_URL` | `http://localhost:9022` | `next.config.ts` rewrite 目标；生产填反代 URL |
| `NEXT_PUBLIC_API_BASE_URL` | `""`（空） | 如需前端直连后端绕过 rewrite 可填 |

## 构建

```bash
npm run build     # next build
npm start         # next start -p 3022
```

## Lint

```bash
npm run lint      # eslint（Next.js 默认规则）
```

格式化由根仓库的 `.prettierrc.json` 控制（`printWidth: 100`，`singleQuote: true`）。

## SSE / 聊天

`/p/[slug]` 的聊天通过 `POST /api/sessions/{id}/chat` 建立 SSE：

- 协议：AI SDK Data Stream Protocol（前缀数字 + JSON 行）
- 前端解析：`lib/sse.ts`
- 事件：`text-delta` / `tool-call-*` / `data-artifact` / `data-subtask-*` / `data-branch-*` / `data-approval-request`
- 详细合约：[`../docs/design/sse-events.md`](../docs/design/sse-events.md)

## 与后端 API 的对应

所有请求走 `/api/*`（Next.js rewrite 到 `BACKEND_URL`）。模块级封装位于 `lib/api/`，与 `../docs/api/` 一一映射：

| 文件 | API 文档 |
| :--- | :--- |
| `lib/api/users.ts` | [`../docs/api/users.md`](../docs/api/users.md) |
| `lib/api/providers.ts` | [`../docs/api/providers.md`](../docs/api/providers.md) |
| `lib/api/agents.ts` | [`../docs/api/agents.md`](../docs/api/agents.md) |
| `lib/api/projects.ts` | [`../docs/api/projects.md`](../docs/api/projects.md) |
| `lib/api/sessions.ts` | [`../docs/api/sessions.md`](../docs/api/sessions.md) |
| `lib/api/memories.ts` | [`../docs/api/memories.md`](../docs/api/memories.md) |
| `lib/api/skills.ts` | [`../docs/api/skills.md`](../docs/api/skills.md) |
| `lib/api/mcp.ts` | [`../docs/api/mcp-servers.md`](../docs/api/mcp-servers.md) |
| `lib/api/storage.ts` | [`../docs/api/storage.md`](../docs/api/storage.md) |
| `lib/api/knowledge.ts` | [`../docs/api/knowledge.md`](../docs/api/knowledge.md) |

## 其它

- 字体走系统栈（不加载 Google Fonts），避免国内网络下 `next/font` 失败。
- 所有 Zustand selector 都取**单字段**，避免返回新对象导致 re-render 死循环。
- `components/ui/*` 严禁导入 `stores/*` 或 `lib/api/*`，保持纯展示。
