# ADR-018 · Mission-only 模型 + 两条迭代回路

**Status**: Accepted (2026-06-17)
**Supersedes**: ADR-006 的 Session/Branch 分层
**Revises**: ADR-015 的 worker 自检宿主 + 迭代路由

## Context

grill(2026-06-17,见架构评审)对 `Mission → Session → Branch → Message` 三层做了删除测试:

- **Session 是 Mission 之上 ~1:1 的 pass-through**。每个 mission 实际只有 1 条 `scope='daemon'` 主会话(`_ensure_super_session` 恒返回同一条);"N 条用户探索 session"是从没落地的 stub(前端 "+ New session" 只弹"pending backend")。memory 按 `project_id`/`branch_id` 存,**与 session 无关**。Session 仅剩的承重点:event_bus 频道键、`scope` 路由、`relay_to_session_id`/`target_project_id` 两个 Builder 字段。
- **Branch 的 rewind 版本分支早被 ADR-006 废**(`branch_number/parent_branch_id/is_current` 字段 deprecated)。唯一还在用的是 **super↔worker 派发线程**(`InvocationContext` 每对 (super,worker) 一条 `super_worker_thread`),承载 worker 的跨次记忆。
- **worker 自检**(ADR-015)是挂 Builder 下的单例 `scope='system'` 会话;**super 自迭代**走 escalation 回 Builder。两者混在 Builder 一处,且 worker 跨 super 共享、super 协议跨自己的 mission 共享,归属不清。

## Decision

### D1 · 数据模型塌缩为 `Mission → Message`

`sessions` / `session_branches` 退役。`messages` 直接带 `(mission_id, thread_key)`:

- `thread_key='main'` —— 用户可见对话流:super 推理(`meta.source` 区分内部/可见)+ 用户对话 + **worker 调用摘要卡**(super 发的 params + worker 返回结果,展开即看)。
- `thread_key='worker:<superId>:<workerId>'` —— 每对 super↔worker 的**持久派发上下文**(双方都记得历史;worker 记忆 = 按此键过滤)。并发锁按 `(super,worker)` 逻辑键,不依赖 branch。

「Thread」从两张表降级成 `messages` 上的一个字符串键。Mission 成为唯一的工作站单元:自己的 memory / schedule(含是否自动执行)/ live / workspace / 一条消息流。

### D2 · 两条迭代回路(对称但不对等)

| | 触发源 | 路由到 | 兼容门 |
|---|---|---|---|
| **super 自迭代** | 该 super 任一运行 mission 发现"super 自身有问题" | **造它的 origin Builder mission**(provenance) | **无硬门**,Builder LLM 在该 mission 对话里判断 |
| **worker 优化** | 任一 super 任一 mission 发现"worker 有问题" | **Colony Worker Optimization super** | **跨调用方门**(L2,ADR-015) |

- **Colony Worker Optimization**:新的单例系统 super —— 不可删/复制、不可新增 mission、自动运行、固定 1 mission。两条输入:① 默认定期自检(读 `worker_invocation_log` 筛退化候选,接替旧 `WorkerHealthSession` 的 6h tick);② 接收所有 super 发来的 worker 优化建议。收到即走跨调用方门优化。**worker 跨 super 共享,所以集中在此一处,不归任何 Builder mission。**
- Builder 只管 **super 创建 + super 迭代**。worker 的**创建**仍由 Builder 在建 super 时做;worker 的**优化**归 Worker-Optimization super(创建 vs 优化分家)。

### D3 · 1:1 provenance

Builder mission ↔ 它产出的 super 是 **1:1**(代码已有"单-super 不变量")。在产出的 super(Agent)上存 `built_by_mission_id`,替代退役的 `session.target_project_id`。产出的 super 自身仍可有 N 个运行实例 mission;每个都是探针。

### D4 · worker 选择 = capability 粒度(1 cap = 1 worker)

super 运行时 `list_workers` 搜目录 → LLM 判断调哪个 capability/action/params → `invoke_worker("capability:<cap>")` 按 capability 动态解析(非写死 UUID);没有则 `request_new_capability` 找 Builder 建。**不引入"同一 capability 多个竞争 worker"**;要多样性用更细的 capability 表达。用过的 capability 沉淀进 Mission/Super memory → 后续可不搜直调,策略写在 protocol。

### 两个非对称(刻意为之,记此以免 review 重提)

1. **super 无门 / worker 有门**:worker 被**不同 super** 共享(不同主、风险大)→ 硬兼容门;super 协议只被**自己的** mission 共享(同一角色)→ 信任 Builder LLM 判断,不设硬门。
2. **1 cap = 1 worker**:capability 即契约,唯一解析无歧义;竞争 worker 会让派发"调了谁"、持久线程"上次跟谁聊"、Worker-Opt"优化哪个"都复杂化,收益不抵。

## Consequences

**+**
- 用户面模型干净:Mission = 工作站,一条消息流;不再有 Session/Branch 的半废弃歧义(正是它在 workbench 里咬到用户的地方)。
- 迭代归属清晰:super→它的 Builder mission;worker→集中的 Worker-Opt super。
- 上下文不爆:thread_key 隔离(worker 内部往返不进 super 主 prompt)+ 分级压缩 + KB 指针 + token-frugal,塌缩后全保留;迭代信号为出站结构化摘要。

**− / 迁移风险**
- event_bus 频道键需从 `session_id` 改 `(mission_id, thread_key)`(主要工作量)。
- `scope` 路由、`relay/target` 需搬到 Mission/Thread 或小表。
- 整表退役须分阶段:先抽 Thread 解析缝(完成 ADR-006 Phase L.2、删死代码)→ 再 messages 加 `thread_key` 双写/回填 → 再切读路径 → 最后 drop 两表。运行中的 daemon 全程不停。
- Worker-Optimization super 需 seed(系统对象)+ 把 `WorkerHealthSession` 逻辑迁过去。

**回退**:迁移期 messages 双带旧 `session_id/branch_id` 与新 `thread_key`,任一阶段可回切读路径。

## 实施进度 / 分阶段落地决定(2026-06-17)

- **Step 1**(完成):抽 Thread 解析缝 `ensure_branch` / `thread_key_for`,删 ADR-006 死代码。
- **Step 2**(完成):`messages.(mission_id, thread_key)` 双写 + 回填(migration 063,Postgres 验证)。
- **Step 3**(完成):切读路径 —— `list_thread_messages`(按 mission/thread 读)+ event_bus 频道键
  `session_id → mission_id` 原子改(全部 publisher + SSE 订阅端)。
- **Step 4**(完成,**与原 D2/D3 范围有调整**):
  - **D2 完整落地**:seed `Colony Worker Optimization` 单例系统 super + 固定 mission;健康自检 tick
    迁宿主到它;`report_worker_issue` 改路由到它(`submit_worker_issue`,不再 escalate Builder);
    保守门控优先(只过 L2 兼容门的可逆改)。
  - **D3 仅列脚手架**:`agents.built_by_mission_id`(migration 064)只**双写不切路由**。原因:
    "super 自迭代 → origin Builder mission" 需要 Builder 会话先成为 mission,而这依赖 step 5 的
    session→mission 塌缩;迁移窗口内 builder 会话仍是单一 builder project 下的 session,此时切
    escalation 到 provenance 会把所有 super 指向同一个 builder project、丢失 per-会话目标。故
    **escalation 路由切到 provenance 推迟到 step 5**。
- **Step 5**(进行中 · 已完成依赖测绘,不可逆 drop 仍 gated):退役 `sessions`/`session_branches`。

### Step 5 依赖测绘结论(2026-06-18)

全量退役**不是一次性删表**,而是 6 个纠缠的子相,因为两表仍深度承载:thread 状态
(`thread_id`/`thread_kind`/`workspace`/全部 `compression_*`)、压缩子系统(`BranchAgentMemory.branch_id`
是压缩唯一键)、Session 路由(`scope`/`relay_to_session_id`/`opened_by`/`status`)、5 处 `messages.branch_id`
读、以及 `ensure_branch`/`InvocationContext`/`_ensure_super_session` 这条返回 `SessionBranch` 的缝。
**几乎没有零风险切片**:唯一纯 write-only 字段 `parent_branch_id` 也由 live 工具 `rollback_to_node` 写。
故按相推进,每相独立 TDD + docker 验证 + checkpoint,云端 drop 永远最后且需显式确认。

| 相 | 内容 | 前置 | 风险 |
|---|---|---|---|
| **A** | 让 `rollback_to_node` 停写 `parent_branch_id` → drop 该列(纯 vestigial) | 无 | 低 |
| **B** | 压缩子系统改键:`BranchAgentMemory(branch_id)` → `ThreadAgentMemory(mission_id, thread_key)`;`maybe_compress_context` / `schedule_compression_if_needed` / `load_history` 全部改读 `(mission_id, thread_key)` | A | **高**(压缩并发/水位线/熔断都挂在 branch) |
| **C** | 改写 5 处 `messages.branch_id` 读 → `list_thread_messages(mission_id, thread_key)`;`append_message` 改为直接收 `(mission_id, thread_key)`(27 caller 签名迁移)→ drop `messages.session_id/branch_id` | B | 高 |
| **D** | builder 会话成 mission(每次 orchestrator chat = 一个 builder mission)→ escalation 路由切 `built_by_mission_id`(完成 D3)→ drop `Session.target_project_id` | C | 中 |
| **E** | `get_current_branch`(读 `is_current`)/`next_branch_number`(读 `branch_number`)改为 thread_key 选主;`SessionBranch`→`Thread` 表,drop `branch_number`/`is_current`/`version_label`/`task_group` | C,D | 中 |
| **F** | ADR-011 relay 改用 message meta 路由 → drop `Session.relay_to_session_id`;最终 drop `sessions` 表 | D,E | 中 |

### 执行中的发现(2026-06-18 · 实施 B 时)

- **B.1 完成**(commit `feb8841`):`ThreadAgentMemory` 表 + 双写镜像 + 回填,纯增量零风险。
- **B.2 完成**(commit `81ee671`):**仅** worker 线程的压缩记忆读切到 thread 表(带 branch 回退)。
- **关键发现 · `main` 线程不唯一 → B/C/D 实为一个纠缠簇**:`thread_key_for` 把所有非 worker/
  非 health 的 branch 都折叠成 `'main'`。但一个 mission(尤其 builder project)下可有**多条** branch
  都 →`'main'`(rollback 版本分支、多条 orchestrator 会话)。于是:
  - **B.2 的 orchestrator/main 记忆**不能切(会跨 build 串记忆)——已留在 branch 键。
  - **B.3 压缩状态**(`compression_in_progress` 是**按 branch 的原子 CAS** `UPDATE ... WHERE id=?`,
    `maybe_compress_context` 按 `branch_id` 选消息)无法在 main 线程唯一前安全改键,且与**相 C**
    (消息读改 `(mission_id, thread_key)`)绑死。
  - 结论:**相 D(让 main 线程按 mission 唯一 —— 核心是 orchestrator 会话各成 mission)是 B(main 部分)/
    C/E/F 的真正前置**,而非 B 在前。剩余工作不是线性 6 相,而是「D 架构核心 → 然后 B/C/E/F 收尾」。

**修订建议**:下一步做**相 D 的架构核心**(orchestrator-会话→独立 mission + main 线程按 mission 唯一),
它解锁其余所有 main 线程改键。worker 线程部分(B.1/B.2)已独立完成。相 D 涉及 builder 多会话模型重构,
应作为独立设计+实现专项;云端 drop 永远最后且 gated。
