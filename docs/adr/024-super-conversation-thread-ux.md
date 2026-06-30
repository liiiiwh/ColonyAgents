# ADR-024 · Super 会话 / Thread / 审批 / Mission 页 UX 重塑

- **状态**: Accepted（2026-06-22，grill 定稿）
- **分支**: `main`
- **相关**: ADR-013（人审）、ADR-018（mission-only thread）、ADR-020（thread_key 三类）、ADR-023（知识/记忆/存储）

## 背景

grill `/mission/<slug>` 工作台，发现一批审批流、thread 语义、布局、调度的不合理点（用户实测 xhs-ops mission）。逐条对照代码后确认根因，集中决策。

## 决策

### A. 审批流
1. **审批卡刷新后又可点（bug）** — `decide()` 只改 `pending_approvals.status` + 补发 `approval_response` 消息，**不回写原卡消息 meta**；前端历史重建无 `resolution` → 按钮复活。**修：读时合并** —— 消息历史接口对带 `request_id` 的审批卡 LEFT JOIN `pending_approvals` 回填 `resolution` + `thread_key`，前端按真实状态禁用（单一真相源 = `pending_approvals`）。
2. **未审批又被重复发卡（bug）** — `_should_skip_tick` 的未决守卫只挡自动 tick；手动 Run Once / 用户消息绕过 → 重发等价卡。**修：`request_approval(force_human)` 创建时未决去重**（同 mission 等价 pending 复用不新建，治本）。
3. **worker 线程显示了 main 的审批（前端 bug）** — 审批卡 mission 级全量混编、不按 thread 过滤。**修：审批卡按 `thread_key` 过滤渲染**（实测审批全属 main，worker 线程本应空）。
4. **MCP 安装审批弹给运营用户（不合理）** — 本地 MCP（git clone/npm/扫码）是技术/管理动作。**修：移出运营 mission 用户审批**，归 Builder/admin 阶段；运营 super 缺该能力时**降级跳过 / 上报 Builder**，不阻塞用户。

### B. Thread 语义
5. `thread` 是**上下文隔离通道**（非"历史调度记录"）：`main`＝人机对话 / `worker:{super}:{worker}`＝super↔worker 内部派发上下文 / `health`＝自检。
6. **worker / health 线程对用户只读** — 后端发消息硬编码 `thread_key='main'` + 前端输入框不按 thread 禁用 → 用户在 worker 线程发的消息错写进 main 并"消失"。**修：worker/health 线程隐藏输入框（只读）**。
7. **删除线程语义** — `main` **禁止删除**（mission 主线）；worker 删除 = "清空该 worker 协作上下文"（改文案）；health 隐藏删除。
8. **worker 线程名显示 UUID** — threads 接口不返可读名。**修：解析 `worker_id → agent.name + capability`**，前端显示可读名。

### C. Mission 页布局重构
9. **左栏只留 Missions 列表**（移除线程区 + 底部"Mission 系统"区——后者只是 super 的 UUID + 与"记忆"tab 重复的清记忆按钮）。
10. **线程移到右侧 tab**（实时 / 调度 / 记忆 / **线程**）；线程列表**只列 worker**（主线程 = 中间默认，不进列表）。
11. **交互**：点左栏 mission = 回该 mission 主线程（输入框可用）；点右侧"线程"tab 的 worker = 中间切到该 worker **只读会话**；**会话窗口顶部面包屑显示当前线程**。
12. **"清记忆"并入右侧"记忆"tab**；super 身份顶部标题已显示，左栏不再单列 UUID。

### D. 调度（super 自迭代敏捷化）
13. super 绑 `schedule_create / update / delete`，**自管自己 mission 的调度**（不再 escalate Builder；Builder 仅建初始）。**规则**：仅限自己 mission；护栏 **每 mission ≤ 5 条 / 触发间隔 ≥ 5min / cron 校验 / 仍受 token_guard**；每次增删改落一条 `main` 消息（用户可见）。

### E. 流式（#3）
14. 后端 daemon tick **已流式**（V7.2 `drive_agent_events`，`mission_daemon.py:527` "非 streaming" 是**过时注释**）。问题在**前端直播渲染** 和/或 **worker 调用过程不流式**（`invoke_worker` 内 worker `ainvoke` 跑完才返回）。**实施时先定位**：super 自身 token 直播是否生效 / 是否要把 worker 执行过程也流式透出。

## 后果
- 正面：审批不再幽灵复活/重复；thread 语义清晰、worker 线程只读、名字可读；左栏清爽、右栏 tab 化；super 调度自管更敏捷。
- 代价：审批读时合并 + 去重、前端布局重构、调度 scope 放开（须配护栏防烧钱）。
- 不可逆点：调度 scope 放开 + 审批去重语义 + thread 删除语义 → 立此 ADR。
- 待定位：E（流式）实施前先确认前端/worker 哪边没流式。
