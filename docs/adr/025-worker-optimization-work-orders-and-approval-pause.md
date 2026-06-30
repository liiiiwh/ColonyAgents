# ADR-025 · Worker 优化 work-order mission 化 + 审批暂停全平台不变式

**Status**: Accepted (2026-06-23)
**Builds on / revises**: ADR-015（worker 自检自迭代闭环，单 mission 内联处理）、ADR-018 D2（Colony Worker Optimization 单例 mission）

## Context

Colony Worker Optimization 是平台唯一管 **worker 优化**的系统级 super（与 Builder 管 super 对称）。ADR-015/018 把它实现为**一个固定单例 mission + 平台级 `sys-worker-health` cron（6h）内联处理**。用户用下来暴露三个真问题：

1. **运行不透明 / 不可调**：6h cron 是 APScheduler 平台 job，没有 `mission_schedules` 行 → 前端「调度」tab 永远显示 0，用户看不到也改不了它，破坏「定义→设好调度→持续跑」心智，看着像「凭空在跑的后门逻辑」。
2. **单 mission 串行 + 易互相打断**：所有体检报告/工单挤同一条 main 线程，多个退化 worker 无法并行处理，上一个没完就被下一个打断。
3. **闭环断 + 易挂起**：super `report_worker_issue` 后停工 `paused_waiting_capability`，但修好后**没人唤醒它**（`resume_super_agent` 是 Builder 专属、且工单没记上报方）→ 僵在 paused 等人工。且平台无「跑到完成」机制（mission 一次 tick=一轮，靠外部触发续跑），自检一轮回复后可能半途挂起。

## Decision

### D1 · Worker 优化改 work-order mission 模型（修订 ADR-018 D2 单例）
- 6h 体检退化为**派发器**：只扫 `worker_invocation_log` 退化候选 → 给每个退化 worker **spawn/attach 一个 ephemeral Work-Order Mission**，派发器自己不修。super 主动 `report_worker_issue` 同理 spawn/attach。
  - **6h 体检节律 = dispatcher mission 的可见 MissionSchedule**（严格 B-1）：`ensure_worker_optimization_super` 给 dispatcher mission 挂一条 6h interval MissionSchedule（调度 tab 可见可调、`is_system`），payload `trigger=worker_health_scan`。fire 时 `run_once` 早路由到**确定性 `run_health_tick`**（纯代码扫描 + fan-out，无退化候选不唤 LLM，保留 ADR-015 省 token）——既满足"可见可调的普通 MissionSchedule"，又不每 6h 空跑 LLM。平台 cron `sys-worker-health` 退役。
- **Work-Order Mission** 盯单个 worker(capability)，全自动（`force_auto_approve`）跑到完成 → **软关闭**（`STOP` + `status=archived` + 注销调度），不 hard-delete（保审计 + 唤醒步骤需读它）。
- **同一 worker 至多一个在跑**（worker protocol 是全局共享单行，并发改必打架）→ 跨 worker 并行、**同 worker 串行去重**（复用 Builder 幂等套路）。`run_once` 不持全局锁，多 mission 真并发可行。

### D2 · 跑到完成：LLM 自驱 + 调度兜底 + max-tick 封顶
- **主路径**：work-order super 协议要求每轮结束时——未完成且没弹 force_human 卡 → 调 `optimization_continue`（入队下一 tick，低延迟）；完成 → 调 `optimization_done`（软关闭 + 按 capability 唤醒等待者 + 注销调度）。
- **兜底**：每个 work-order mission 挂**短间隔 MissionSchedule**。lifecycle 天然做闸门——running 未完成→补踢；archived→no-op；paused→被跳过（见 D3）。LLM 漏调续跑也不会静默挂起。
- **封顶**：`run_count > max-tick` → 强制 `optimization_done("未能自动修复")` + 唤醒等待者（免上报方永久 paused）+ 注销调度，防修不动的 worker 无限重踢烧 token。
- `optimization_continue` 守卫：有未决 `force_human` 卡时**拒绝入队**（不得越过人工门）。

### D3 · 审批暂停全平台不变式
**存在 pending 审批卡 ⟺ mission `paused_clarification`**，且**至多一张 pending 卡**——落卡时 `cancel_event.set()` 砍断本轮 ReAct + 立即 pause 不再 tick，无从产生第二张，故无多卡场景。四个触点：
1. `request_approval` 落卡处（`if not auto_approve`）→ `transition(PAUSE_FOR_CLARIFICATION)`。
2. `_should_skip_tick` 补 `paused_clarification` 也跳（原只跳 `paused_waiting_capability`）→ 调度器/cron 无法 tick 暂停态。
3. 答卡恢复（`pending_approval_service.respond`）→ 卡 decided + `RESOLVE_CLARIFICATION`→running 再触发 tick。
4. 用户消息恢复（`super_conversation`）→ 把那张 pending 卡**关闭置灰**（status→closed/superseded，前端不可再操作，复用既有置灰渲染）+ `RESOLVE_CLARIFICATION`→running 再触发；用户消息接管驱动。

边界：auto 模式普通审批**瞬时自动通过、不落卡** → 不暂停照跑；`force_human=True` 无视 auto **必落卡** → 必暂停等真人。

## Considered alternatives

- **保留单例 mission + 仅把 cron 显示成只读调度条**（最小改动）：解了透明度(问题1)，但不解并行(问题2)与跑到完成(问题3)，被否。
- **post-tick 确定性钩子做续跑兜底**（仿 build_finalizer）：可行，但「调度兜底」更省——mission lifecycle 已天然区分 done(archived,no-op) / hung(running,补踢) / 等人(paused,skip)，无需新钩子。采纳调度方案。
- **hard-delete 关闭 work-order**：丢审计轨迹 + 破坏「先读记录再唤醒等待者」时序，改软归档。
- **仅 force_human 才 pause**（窄版）：用户要求收敛为「任何 pending 卡都 pause」更普适的不变式（D3），取代窄版。

## Consequences

- ✅ worker 优化与 Builder 真正对称：系统级不可删 super + 可见可调度 + 功能完整；运行不再「凭空」。
- ✅ 多退化 worker 并行修、互不打断；同 worker 串行防全局 protocol 互踩。
- ✅ 上报→修复→唤醒闭环自动闭合（按 capability，确定性，不依赖人工/Builder）。
- ⚠️ D3 是**平台级行为变更**（所有 super 的真人审批都会真 pause mission）：对交互 super 是改善（UI 真显示「等待人工」），但必须保证答卡/用户消息两条恢复路径都接通，否则 mission 困死——故作独立 TDD 切片先行。
- ⚠️ work-order 全自动 + 兜底调度若 max-tick 设太大，修不动的 worker 仍会持续重试若干轮——封顶值需随真实流量校准。
- ⚠️ ADR-015 的「无候选不唤起 LLM 省 token」在派发器层保留（扫描是纯代码），但每个 work-order 至少一轮 LLM；ephemeral mission 数量随退化 worker 数增长。
