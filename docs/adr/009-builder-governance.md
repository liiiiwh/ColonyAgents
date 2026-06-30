# ADR-009 · Builder 治理闭环 · 跨 super 兼容硬阻断 + worker 健康上报 + 多 session 互斥 + 工作记录

**Status**: Accepted (2026-06-03)
**Builds on**: ADR-007（v7 统一流式 / idle-trigger）、ADR-008（生产就绪 / Builder 工厂硬门）

## Context

审计「super↔Builder 能力治理闭环」（证据核到代码行）结论：

| 能力 | 现状 | 缺口 |
|---|---|---|
| super 向 Builder 汇报缺 capability + 暂停 + 重激活 | **通**（request_new_capability → escalation → paused_waiting_capability → resume_super_agent） | 汇报后**不自动唤醒 Builder**；现有 worker **坏掉**无专门上报、不暂停 |
| Builder 改共享 worker 的**跨 super 兼容** | **无防护** | worker 平台共享、改完立即对所有 super 生效；backward_compat 只孤立比新旧契约，**无「哪些 super 在用」查询、无 per-super 遥测、无改前影响分析** → 「一边好一边坏」 |
| Builder 多 session 同时改同一 worker/super/skill | **无防护** | 两个 session 并发 mutate 同一目标会互相覆盖 |
| Builder per-session 工作记录 | **部分** | 只有 chat + memory_append；无结构化变更审计 |
| Builder 新建 skill | **部分** | 只能装已有（ClawHub）；无法创建全新 skill，与 P5 硬门冲突时卡死 |

## Decision

### G1 · 跨 super 影响分析 + 硬阻断不兼容（Q3 · 最关键）
- `find_supers_using_capability(db, capability) → [{super_agent_id, project_id, slug, source}]`：**声明用量**（agent.extra_config.required_capabilities）∪ **观测用量**（worker_invocation_log 近 N 天按 caller super 聚合）。
- per-super 遥测：worker_invocation_log 加 super 维度聚合（`worker_telemetry` 增 `per_super`）。
- `apply_worker_spec` 升级既有 worker 时：枚举消费 super → 对每个跑 `check_backward_compat`（新契约 vs 该 super 依赖的 action 集）→ **只要有一个 super 会被破坏就 raise**（返回 `breaking_supers` 列表），Builder 必须改成兼容（deprecated_actions / 只加 optional）或先升级那些 super。**硬阻断，杜绝「一边好一边坏」。**

### G2 · worker 健康上报 + 触发暂停（worker health）
- 新增 super 侧 skill `report_worker_issue(capability, evidence, severity)`：区别于「缺 capability」，上报「现有 worker 反复失败/行为异常」。
- 走 `project_escalate_to_builder`（category=`worker_health`，新类）+ 让 super 进入 `paused_waiting_capability`（paused_reason 前缀 `worker_issue:` 区分；复用既有 daemon skip gate + `resume_super_agent` 恢复路径，不新增 FSM 态）。

### G3 · escalation 立即唤醒 Builder（auto-wake）
- `escalation_dispatcher.deliver_escalation` 投完消息后：若 Builder project idle → **idle-trigger 一轮 Builder tick**（复用 v7 `_trigger_tick_async` + `should_trigger_now`）。闭环真正自动，不再等人来撩 Builder。

### G4 · Builder 多 session 互斥锁（防竞争 · 用户新增）
- 新表 `builder_work_claim`：`(target_type, target_id)` 唯一 → `(session_id, project_id, status, claimed_at)`。target_type ∈ {`worker`,`super`,`skill`}。
- Builder mutation skills（build_worker/build_super/install_skill/resume_super_agent/report 处理）**先 acquire claim**（scoped 到当前 session）：
  - 无人持有 → 获取，继续；
  - 被**其它 session** 持有 → **拒绝**并告知「另一 session 正在处理该 {target}，请等其完成或切到那个 session」；
  - 本 session 已持有 → 复用（幂等）。
- 完成（成功/失败终态）释放。纯决策 `decide_claim(existing, requester_session) → grant|reject|reuse` 可独测。

### G5 · Builder per-session 结构化工作记录（Q4）
- 新表 `builder_work_log`：`(session_id, project_id, ts, action, target_type, target_id, affected_supers, result, summary)`。
- factory/skill mutation 成功后写一行（创建/升级了什么 agent/skill/worker、影响了哪些 super、escalation 处理结果）。
- 前端 mission 页（builder）加「本 session 工作记录」视图（读 builder_work_log）。

### G6 · Builder 新建 skill 能力（Q5 · 受限）
- **不允许运行时跑任意新代码**。提供「受限模板化 skill 创建」：`create_skill_from_template(slug, name, kind, template, config)` —— 仅支持白名单模板（如 `http_api_call` / `mcp_proxy` / `prompt_macro`），参数化生成 skill 行（builtin_ref 指向通用执行器 + config 驱动），不引入任意代码。
- 同时让 P5 硬门在 skill 真缺失时**优雅降级**：Builder 收到结构化 `{missing_skills, hint}`，可选择 `install_skill`（ClawHub）/ `create_skill_from_template` / 向人求助，而非死循环。

## Rollout（TDD 分阶段 · 依赖序）

- **G1** 跨 super 兼容（最关键，先做）：consumer 查询 + per-super 遥测 + impact 分析硬阻断
- **G4** 多 session 互斥锁（mutation 安全底座，G2/G5/G6 都依赖）
- **G2** worker 健康上报 + 暂停
- **G3** escalation auto-wake Builder
- **G5** per-session 工作记录（+ 前端视图）
- **G6** 受限模板化 skill 创建 + P5 优雅降级
- **E2E**：真实 LLM 驱动 —— super 上报坏 worker → Builder 被唤醒 → 改 worker 时硬阻断跨 super 破坏 → 兼容升级 → resume super；并发第二 session 改同一 worker 被拒。

## Consequences

**+**：能力治理闭环真正自动且安全；「不能一边好一边坏」有事前硬阻断；Builder 多 session 不打架；每 session 可审计；skill 缺失不再卡死。

**−**：worker 升级多了跨 super 校验成本（可接受，安全优先）；新增 2 张表（claim/work_log）+ 1 个 escalation 类 + 受限 skill 模板执行器。

## 命名（加入 CONTEXT.md）
- **CapabilityConsumer**：在用某 capability 的 super（声明 ∪ 观测）
- **WorkerChangeImpact**：改 worker 前的跨 super 影响分析结果（safe / breaking_supers）
- **BuilderWorkClaim**：Builder session 对某 mutation 目标（worker/super/skill）的独占锁
- **BuilderWorkLog**：Builder 每 session 的结构化变更审计
- **report_worker_issue / create_skill_from_template**：新增 super/Builder skill
