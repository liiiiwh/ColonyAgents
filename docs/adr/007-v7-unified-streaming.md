# ADR-007 · v7 Unified Streaming Model · Chat 消息为唯一真相源，退役 ActivityTree

**Status**: Accepted (2026-06-02)
**Supersedes**: v6.I/J Activity backbone（`agent_activities` 表 + ActivityRecorder + ActivityTree UI + Intervene-on-activity）

## Context

v6.I/J 把 `agent_activities` 立为「first-class 可观测 backbone」：一棵 super tick 的活动树，
前端用 ActivityTree / ChatTickCard 渲染。但实战暴露两套割裂：

1. **两条执行路径**
   - `stream_chat_reply`（`/sessions/{id}/chat`）：`astream_events` 流式，**每个 LLM/tool 事件落成 agent_log 消息**（meta.raw 带完整事件），前端 `toTimeline` 重建完整时间线 —— 全细节可见
   - `project_daemon.run_once`（cron + super_chat 触发）：`executor.ainvoke` 一次性，**只落 final_text** —— daemon 黑盒

2. **两条 SSE 通道 + 两套观测**
   - AI SDK 文本流（token 级）
   - event_bus 生命周期/活动流（ActivityTree）

   导致同一份「super 在干嘛」要维护两套渲染（chat 时间线 vs ActivityTree 树），且 daemon 的细节
   两套都进不去 —— 实时可观测性审计（R5）确认 `LLM_CALL / THINKING / MEMORY_OP / KNOWLEDGE_OP`
   全程不记录。

3. **可观测性审计结论**：worker 链路满分，**supervisor 自身推理盲区**。根因是 daemon 不走流式路径。

## Decision

**统一为单执行路径 + 单真相源：一切皆 chat 消息。**

```
StreamingExecutor (Layer 1 · 共享执行核心)
  · astream_events → event_translator 翻译 → yield (event, persist_action)
  ├── HTTP sink (Layer 2a)     → /sessions/{id}/chat：yield SSE 给客户端 + persist
  └── daemon sink (Layer 2b)   → daemon tick：每事件 append_message → event_bus → /super/{slug}/stream 转发
```

关键不变式：
- **chat 消息（agent_log + meta.raw）= 唯一观测真相源**。LLM call / thinking / tool / worker / approval
  全部以消息形式进 session chat，按 `tick_id`/`turn_id` 折叠成卡片（复用 ChatTickCard，但**由消息驱动**，不读 agent_activities）
- **daemon 第一次拥有流式 + 逐事件落库**：cron tick 的细节和用户 chat 一样实时进会话上下文
- **删除 `agent_activities`**（表 + ActivityRecorder + ActivityTree UI + useActivityStream + ChatTickCard 树版）
  - `Intervene`（Phase K）改为对 chat 里的 approval / clarification / redirect 卡片操作（消息级）
  - Builder telemetry 只读 `worker_invocation_log`
- **tick 边界插入**（不再 cancel）：用户消息进 `pending_queue`；当前 tick 的 astream 一结束，StreamingExecutor
  自动抽 pending → 立即开下一 tick（全 thread 历史 + 新消息自然接上）。super idle 时用户消息立即触发新 tick
- **行为步道标签**：§3 用户消息标 `[👤 用户实时插话·优先响应·人在现场]`，cron 触发标 `[⏰ 定时自主运行]`；
  `protocol_md` 教 super 见用户标签先回应再推进既定计划。`meta.source` 同时供后端路由
- **cron 去重**：不加硬去重。super tick 进来时读 mission memory / 消息历史自判今日是否已做（靠 protocol + memory）

## Rollout（分阶段，TDD）

**Phase V7.1 · StreamingExecutor 抽取（不改行为）**
- 从 `stream_chat_reply` 抽 Layer 1 `app/services/streaming_executor.py`：纯执行核心 yield 事件序列
- `stream_chat_reply` 改成 HTTP sink 适配器（行为不变，回归测试守住）

**Phase V7.2 · daemon 走流式**
- `project_daemon.run_once` 改用 StreamingExecutor + daemon sink（persist 每事件 → event_bus）
- daemon 细节首次进 session chat
- tick 边界 auto-drain pending（移除 cancel_current_tick 的 cancel 语义，改成「完即抽」）

**Phase V7.3 · 行为标签 + cron 自判**
- daemon_prompts §3 加用户/cron 标签；super protocol_md 加优先响应 + 今日去重规则

**Phase V7.4 · 退役 ActivityTree（⚠️ 门控：需 app 能跑起来后做，destructive + UI 依赖）**
- 前端：删 ActivityTree 面板 + useActivityStream + ChatTickCard 树版；chat 时间线按 tick_id 折叠（消息驱动）
- intervene 改 message-card 化（对 chat 里 approval/clarification 卡片操作）
- migration：drop `agent_activities` 表（telemetry 切 worker_invocation_log）
- **⚠️ 修正（实测发现）**：`dispatch_to_worker`/`parallel_dispatch` **不能删** —— Builder Supervisor 的
  protocol_md（init_db.py:342-345）用它们做 node 编排（builder_planner/assembler/installer 流水线）。
  删它们要重写整个 Builder 流程，**不在 v7 范围**。只保留 R2-5 的 deprecated 标记，Mission super 用 invoke_worker，Builder super 继续用 dispatch_to_worker。
- **为什么门控**：删表/删前端组件/改 intervene 都是 destructive 且依赖运行 UI 验证；项目当前跑不起来 +
  集成测试被 JSONB conftest 阻塞，盲删会 ship 破坏。V7.0-V7.3 已交付核心价值（daemon 流式进 chat）；
  ActivityTree 变成 redundant-but-harmless，等 app 跑起来 + 验证 message-driven chat 显示 daemon 细节后再删。

## Consequences

**+**
- 单一观测模型：所有「super 在干嘛」只在 chat 时间线，daemon 不再黑盒
- 删一整套并行渲染（ActivityTree / useActivityStream / agent_activities 写读）
- 用户体感：cron 跑数据分析时，每步 LLM/worker 实时进会话，像看 super 直播

**−**
- 一次性重写 daemon 执行核心（V7.2 风险最高）；分阶段 + 回归测试缓解
- intervene 需重做（message-card 化）
- agent_activities 历史数据丢弃（无害，本就只读）

**回退**：StreamingExecutor 抽取是 additive；V7.2 前 daemon 仍可走老 ainvoke。drop 表是最后一步，前面阶段都可回退。

## 命名禁忌（防未来 review 重提）
- ❌ ActivityTree / agent_activities / ActivityRecorder —— v7 已退役，不要再建议「补 Activity 观测」
- ❌ 「两条 SSE 通道」当设计 —— v7 是单真相源（chat 消息）；token 流是 chat 的实现细节不是第二套观测
- ✅ 要观测 super 某步 → 让它落成 chat 消息（agent_log + meta.raw），别建结构化活动表
