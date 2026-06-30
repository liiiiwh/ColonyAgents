# UI 清扫 · 问题登记册（统一修复用）

## ✅ 已修复（overnight 批次 · P1–P4）
- **HIGH** self_tune `base_row.created_at`→`applied_at`（ADR-015 跨调用方兼容门之前形同虚设，已修）。
- **HIGH** SSE `streamUrl` 硬编码 localhost:9022 → 改同源（生产 mission 直播黑屏修复）。
- **MED** fire-and-forget 任务可被 GC（escalation/approval ×3）→ 新增 `app/core/bg_tasks.spawn` 强引用持有（TDD 1 测试）。
- **MED** admin layout 非 admin 仍渲染后台 + 触发 admin API → render 门加 `role==='admin'`。
- **MED** mission redirects 卡按 index 过滤删错卡 → 改按对象引用过滤。
- **MED** storage 会话过滤名不副实 → grouped 跨层按 session_id 过滤。
- **LOW→修** 默认模型 lifecycle_status 缺失（agents badge）；mcp 命令行引号参数；Badge 暗色+destructive；knowledge failed 态；404/error 页。
- 死代码清理：ChatArea/WorkspacePanel 簇（~4500 行）、admin-context.ts、recent-project.ts、_placeholder.py、ProjectHomePage + p/[slug] 全部 4 个死文件。

## ⏳ P4 扫描剩余 LOW（已记，未改 · 影响小）
- worker 页 `const [window,...]` 遮蔽全局 window（无害 footgun，建议 rename timeWindow）。
- SSE EventSource token 过期（~30min）不刷新 → 长连断后重连仍 401；需开连接前 ensureFreshToken。
- `project_deleted`/`error`/`done` SSE 事件无 handler（删 mission 后工作台不自知）。
- worker 调用阶段标签 `🔍 解析` 等未 i18n（lib/sse/handlers.ts）。
- 多个 admin handler 仍可能吞错（部分已随 dialog 迁移加 toast；knowledge/materials/schedule 残留可补 try/catch）。
- `/super/<slug>` → `/mission/<slug>` 多一跳重定向（agents/worker 链接可直连 mission）。
- storage mission 过滤用 project.id 拼 prefix；若 project.id≠mission_id 则空（需确认二者相等）。

## ✅ 已修复（早先轮次）
- mcp 命令行 `split(/\s+/)` 拆坏引号参数 → `lib/shell/splitArgs.ts`（TDD，6 测试绿）+ 接入 mcp 页。
- Badge 组件硬编码 emerald/amber（暗色破）+ 缺 destructive → 全改语义 token + 加 destructive 变体（全站 badge 一次修好）；knowledge failed 态改 destructive。
- 死代码 ChatArea/WorkspacePanel + AgentStatusPill/JsonFormEditor/SpecPreview/BranchList（~4500 行）→ 抽出 FormRequestCard 后删除，tsc 0 错。
- 全局控件遮挡工作台顶栏 → header pr-32；工作台 CTA `/super/`→`/mission/`；superRole「Ask Builder」→ `/mission/builder`。
- tailwind 注册 success/warning/info 颜色（之前彩色提示底不渲染）。

## ⏳ 仍未修（较大/需后端改，已留清晰修法，未在本轮硬上）
- 🐞 **storage 会话过滤名不副实**：选 session 仅子串筛当前层文件;真修需后端按 session_id 跨层查询（中等工作量）。
- 🐞 **agents mission badge `lifecycle_status` 落空**：projects 列表 API 未返回该字段 → badge 退默认色。修法:ProjectPublic schema + projects 列表 endpoint 补 `lifecycle_status`（后端小改 + 前端类型）。
- 📝 **原生 confirm()/alert() 未主题化**（users/storage/materials/workbench 等多处）→ 迁到主题化 Dialog/Toast（跨多文件，较大）。
- 📝 worker 卡 EN/ZH「Active missions / 活跃 Super 数」其实指「活跃 super 数」——EN 译反了,应 EN 也用 supers;低优先、可议。
- 🔗 `/admin/clawbot` 路由名 + `clawbotApi` 仍带历史名（渠道抽象化时再动）。

---


> 逐页清扫(暗色适配 + i18n + 文案)过程中发现的**功能/逻辑/业务文案**问题集中记此处，**暂不即修**，攒齐后统一处理。
> 清扫本身的「暗色 + i18n + 明显过时文案」就地改；这里只记需要单独决策/改逻辑/跨页的问题。

图例：🐞 功能/逻辑 bug ｜ 📝 文案与业务逻辑不符 ｜ 🔗 死链/路由 ｜ ❓ 待确认

---

## admin 概览 `/admin`  ✅ 已扫（我亲扫 · 内容重写）
- 📝（已就地处理）原页满是内部实现术语（project_daemon / V22/V53 守卫 / worker_invocation_log）+ 内部 ASCII 架构图 → **重写为用户视角 4 步「How Colony works」+ 快速入口**，删掉内部 ASCII graph 与 showGraph toggle（对 OSS 用户无意义、暴露内部细节）。

## admin MCP Servers `/admin/mcp-servers`  ✅ 已扫（子代理）
- 🐞 `commandLine.trim().split(/\s+/)` 朴素空格切分会拆坏含空格的引号参数/路径。
- 📝 测试失败时状态格直接显示后端 `r.msg`（可能英文，未 i18n）。

## admin Knowledge `/admin/knowledge`  ✅ 已扫（子代理）
- 🐞 文档 `failed` 状态用中性 Badge variant，与正常态视觉无区别（应 destructive）。

## admin System Settings `/admin/system-settings`  ✅ 已扫（子代理）
- 📝 `emptyHint` 原引用「migration 038/041」开发术语（已泛化为「数据库迁移」）；admin 多为非工程师，过技术。
- 🐞 onSave JSON 解析：裸输入 `true` 会被强制成布尔（历史行为，未改）。
- 📝 `Project.compression_config` 作代码标识符保留；若后端字段改名 Mission 需同步。

## admin Agents `/admin/agents`
- （待扫）

## admin Providers `/admin/providers`  ✅ 已扫（dark + i18n；#7 支持类型说明已在）
- 📝 子组件 `components/providers/ProviderDialog.tsx`、`ModelsTable.tsx` 仍含硬编码中文 + 颜色 → 待扫。

## admin Users `/admin/users`  ✅ 已扫（子代理；待并 catalog）
- 🐞 `Plus`（lucide-react）import 未使用（历史遗留）。
- 📝 confirm()/alert() 原生弹窗未主题化（与暗色设计不符）→ 后续迁到主题化 Dialog。
- ❓ 文案已 `项目→Mission`；需确认运行时导航路由是否仍字面 `/projects`。

## admin Storage `/admin/storage`  ✅ 已扫（子代理；待并 catalog）
- 🐞 **Meshy 快捷入口仍在**（我已删 meshy 后端）→ 死 prefix `colony/meshy/`。**应移除该 quick-link**（meshy QuickIcon 分支一并删）。
- 🐞 会话过滤非功能性：选 session 只 alert + 按 key 子串筛当前层文件，但 session 文件在更深子目录，mission 层时几乎筛不到。
- ❓ QUICK_LINKS 模块级常量改为存 labelKey/hintKey 渲染时 t()——确认此模式 OK。

## 审核渠道 `/admin/clawbot`  ✅ 已扫（dark + i18n + 改名 + coming-soon 提示）
- 📝 路由名仍是 `clawbot`（历史名），菜单/页面已改「审核渠道」；路由 slug 后续可考虑改名（低优先，改动大）。
- ❓ `clawbotApi`/`approvals.ts` 命名仍带 clawbot；若渠道抽象化（后续接 Slack 等）需把 API 层抽象成「channel provider」，当前仅微信先不动。

## admin Skills `/admin/skills`  ✅ 已扫（子代理；已并 catalog）
- 🐞（已就地修）install 结果原先靠 `installMsg.startsWith('✅')` 判成功色，i18n 去 emoji 后会失效 → 子代理改用显式 `installOk` 布尔。
- 📝 `installSuccess` 原模板有空 `@${''}`（永远渲染 '@'）→ 去掉；若要显版本需 install API 返回 version 字段。

## admin Materials `/admin/materials`  ✅ 已扫（子代理；已并 catalog）
- 📝 副标题含内联 `<code>` 拆成 prefix/mid/suffix 三 key；若引入 `<Trans>` 组件可单 key 带标记更干净。
- ❓ 无 `项目/Project/v4` 过时词。

## admin Agents `/admin/agents`  ✅ 已扫（子代理 + lifecycle 修正）
- ✅（已就地修）Super 列表不再显示「未绑定 Project」假缺陷 → 改「运营实例数 / Template·无实例」+ System 徽标。
- ❓ mission badge 读 `(m as any).lifecycle_status`，该字段不在 ProjectPublic 类型；若 API 不返回则所有 badge 落默认色 → 需确认 projectsApi.list() 是否带 lifecycle_status。
- 📝 「Ask Builder」CTA 由实心 amber 改成 warning 浅底（按 token 映射），视觉权重下降——可考虑给它 primary 实心。

## admin Agent 详情 `/admin/agents/[id]`  ✅ 已扫（子代理）
- 🔗 Protocol 区链接 `/docs/design/supervisor-protocol.md`(target=_blank) 是服务端 doc 路径,非 Next 路由 → 应用内点击大概率 404。
- 📝 多处原生 confirm()/alert()(未主题化)。

## /worker /observe /orchestrator /projects  ✅ 已扫
- 📝 worker 页 EN/ZH 术语分叉:EN 用 Mission、ZH 仍 Super(如「Active missions / 活跃 Super 数」「Per-Mission / Per-Super」)——建议统一 ZH 也改 Mission/运营实例。
- ❓ worker 「性能&失败分析」/token 卡在后端无数据时显示 '-'(P1 已修写入路径;待真实流量验证)。
- observe / orchestrator 均为 redirect stub。

## 🔧 跨页根因修复（本轮就地修，影响所有已扫页）
- ✅ **tailwind 未注册 `success/warning/info` 颜色** → `bg-success/10`、`bg-warning/10`、`border-warning/40` 等之前**完全不渲染**。已在 tailwind.config 注册三色 + 删 globals 里手写的 .text-success/.warning/.info（Tailwind 现自动生成）。这是所有子代理页「彩色提示底」生效的前提。

## 工作台 + chat 组件 `/mission/[slug]` `/super/[slug]` `components/{chat,super,mission}/*`  ✅ 已扫（5 子代理）
- 🐞 工作台 CTA 卡 `window.open('/super/'+pslug)` 是过时路由(super→mission 改名后),应为 `/mission/`。
- 🐞（已就地修）工作台 `threads.map((t)=>)` 的 `t` 遮蔽了 i18n 的 `t` → 子代理改名 `th`。
- 🔗 superRole「Ask Builder」链接硬编码 `/super/Builder Supervisor`(带空格),依赖该名 super 存在,否则进 not-found。
- ❓ 工作台「+ 新建 Session」按钮仅 alert(后端未就绪),非功能 stub。
- 📝 AutoApproveToggle 实心按钮用 `bg-warning text-background`(缺 `--warning-foreground`/`--success-foreground` token)→ 建议补这两个 foreground token,实心 success/warning 按钮才有规范文字色。

## 🐞 全局控件遮挡(本轮新发现,跨页)
- **固定右上角 EN/中+主题控件 与「自带顶栏右侧操作」的页面冲突**:工作台 `/mission/[slug]` 顶栏右侧(Run Once/Start/Stop/Restart/刷新 + AutoApproveToggle)被全局控件压住重叠。修法:这类满铺顶栏页给 header 右侧留出 ~140px padding 避让,或工作台顶栏把全局控件纳入自身布局。

## 🧹 疑似死代码（待确认后清理，本轮不扫）
- `components/chat/ChatArea.tsx`（2748 行）+ `components/chat/WorkspacePanel.tsx`（1244 行）**无任何 `<ChatArea>`/`<WorkspacePanel>` JSX 渲染处** → 整体疑似废弃（仅 `FormRequestCard`(ChatArea 内导出) 被 mission 页用）。建议：把 `FormRequestCard` 抽到独立小文件，删 ChatArea/WorkspacePanel 本体。其依赖(SpecPreview/BranchList/AgentStatusPill/JsonFormEditor)若仅服务它们则一并清。**这能省掉 ~4500 行的暗色+i18n 清扫。**

## 跨页通用问题
- 📝 users / storage / materials 多处用原生 `confirm()`/`alert()`（已 i18n 但**非主题化**，与暗色设计不符）→ 后续统一迁到主题化 Dialog/Toast。
- ❓ `Messages = typeof en`（去 `as const`）现强制 en/zh **key 结构对齐**（tsc 守护）；新增页务必两边同步加 key。

## 其它页（待扫）
- 我亲扫：/admin (概览) /admin/agents /admin/agents/[id] · 工作台 /mission/[slug] /super/[slug] /observe/[slug] /worker/[id] /orchestrator /projects /p/[slug]
- 子组件：components/providers/ProviderDialog + ModelsTable
- 下一波长尾并行：/admin/mcp-servers /admin/knowledge /admin/system-settings
