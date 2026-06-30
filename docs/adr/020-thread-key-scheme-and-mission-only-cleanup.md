# ADR-020 · thread_key 干净命名 + mission-only 收尾 + 架构深化

- **状态**: Accepted（2026-06-21，grill 定稿）
- **分支**: `adr-018-mission-only`
- **相关**: ADR-018（mission-only）、ADR-019、架构评审报告（improve-codebase-architecture，2026-06-21）

## 背景

ADR-018 收口了 Session/Branch 表，但留了三处尾巴（grill 时被用户截图抓到：mission 页左栏仍显示「Sessions (11)」、11 条同名 "Main line"、点不开）：

1. **前端术语未改**：i18n 仍 `Sessions / Main line / session`，左栏概念还是会话列表。
2. **数据脏**：云测库 builder mission 有 11 条历史 thread_key（2026-06-18 迁移前），都被归类成 main-ish。
3. **thread_key 命名不一致**：super↔worker 同时存在 `super-{sid8}-worker-{wid8}`（截断）与 `worker:{superId}:{workerId}` 两种格式；`main` 分类规则把多种 branch 折叠成 'main'（架构评审 candidate 2）。

架构评审另指出 5 个深化点（candidate 1-5），其中 1-3 同源于本迁移尾巴。用户裁定（v1 未发布、无需兼容、直接清干净）：**全做 1-5 + 收尾**。

## 决策

### D1 · thread_key 只有三类干净键（全 UUID）
- `main`：super 主运行流 + 用户对话，**每 mission 恒 1 条**。
- `worker:{super_id}:{worker_id}`：super↔worker 持久派发上下文，**全 UUID 不截断**。废弃 `super-{sid8}-worker-{wid8}` 旧格式（`InvocationContext.thread_id` 改全 UUID）。
- `health`：系统 worker 健康自检。
- **取消** orchestrator/builder/legacy 线程类——mission-only 下 builder 对话即 builder mission 的 `main`。
- 截断格式碰撞风险虽低（mission 内 worker 数少），但选全 UUID 求**命名即身份、无歧义、可断言**（candidate 2）。
- `thread_key_for` 纯函数过浅（12 行 3 分支、几乎无人调用、'main' 歧义）→ 内联到调用点，命名约定成为唯一真相。

### D2 · 前端术语 Session → Thread；左栏只展示有意义线程
- i18n / 组件一律「Thread/线程」，删 `sessions/mainLine/deleteSession*` 旧文案语义。
- 左栏下半列 thread：main（恒 1）+ 活跃 worker 线程 + health；不再出现多条 "main"。点击经 `exportThread(thread_key)` 拉消息。

### D3 · 数据清理（云测库，已授权）
- builder mission 历史多 main + `super-xxx8` 旧键：直接删（测试库，v1 未发布）。保证每 mission 恒 1 条 main。

### D4 · 架构深化（candidate 1-5 全做）
1. **删 `BuiltinToolContext.session_id/branch_id`**（迁移 071 已删 DB 列，context 仍暴露 + ~多处散读）→ 统一 (project_id, thread_key)。
2. thread_key 命名统一（= D1）。
3. **`ThreadCompressionManager`**：把 session_service 的 maybe_compress/upsert_thread_memory/水位线/OCC/去重收成单入口深模块，返回结构化结果；9 个调用方变一行。
4. **`should_skip_tick(mission, payload, db) → (skip, reason, detail)`**：project_daemon.run_once 头部三处守卫前置集中。
5. **`WorkerInvoker`**：invoke_worker / parallel_dispatch 的「锁→解析→dispatch→解析 envelope」收成编排器，消除重复 + 统一锁。

## 后果
- 正面：mission-only 在数据/代码/UI 三面真正收口；thread 身份唯一自解释；压缩/编排/守卫各成深模块，可单测。
- 代价：thread_key 改名是数据迁移（仅清测库，无生产）；5 项深化是一轮较大重构（TDD 分片提交）。
- 不可逆点：thread_key scheme（messages + worker 记忆主键）—— 故立此 ADR。

## 执行记录与候选复核（2026-06-21，对照真实代码）

落地后对照代码复核 D4 五候选，两条与评审快照不符，据实调整：

- **candidate 1（删 context 字段）= done**（Slice B）。
- **candidate 2（thread_key 命名）= done**（Slice A）。
- **candidate 3（ThreadCompressionManager）= 不做（premise 失效）**：评审称「9 个调用方 + OCC 泄漏」，实查 `maybe_compress_context`/`schedule_compression_if_needed` **无任何活调用方**（ADR-018 删 stream_service 时压缩被孤立）。为 0 调用方抽深模块违反 no-bloat。**真问题是压缩未接线**（云端 builder main 已 950 msgs）——这是 feature regression，**re-wire 是独立功能决策**（触发点 = daemon tick？keying 需匹配 reader：worker 线程读 `worker_conversation`、main 读 `agent_node_name`）。**flag 给用户决定，未自行恢复**。
- **candidate 4（should_skip_tick）= done**：daemon `run_once` 三守卫判定集中到只读 `_should_skip_tick`，副作用留 run_once。
- **candidate 5（WorkerInvoker）= 已是目标态，无需改**：复核发现 `invoke_worker_tool` 与 `invoke_workers_parallel_tool` **都已薄壳委派给单一 `_invoke_worker_inner`**（lock→resolve→dispatch→parse 的统一编排器）——**无重复**。评审快照过时（看的是 _invoke_worker_inner 抽出前）。再包一层 WorkerInvoker class 是纯 churn（deletion test：删了只会内联回去，它已经是深模块）。

### 压缩 re-wire（candidate 3 的真问题）= done
接回 `maybe_compress_context` 两处（daemon 主线 node='supervisor' / invoke_worker 线 node='worker_conversation'，均在 build_executor 前，best-effort），并加读回键一致性测试。不抽 ThreadCompressionManager 壳层（该函数本身即单一干净入口）。
