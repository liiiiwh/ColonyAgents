# ADR-029 · SSE 实时下发可靠性（approval_request 零延迟 + event_bus 重放缓冲）

**Status**: Accepted (2026-07-01)
**Builds on**: ADR-025（审批暂停不变式）、ADR-028 D4（生命周期门控 · H1 人工门落卡硬停当前 tick）、v5 event_bus（进程内 fire-and-forget pub/sub）

## Context

真实运行反复出现：super 设计会话跑到「请审核」落卡后，前端审批卡渲染成 **⏹️已关闭（无需处理）不可点**，必须手动刷新一次才变可点。用户诉求：**所有内容实时、无延迟下发**，不靠刷新。

逐层实测（给 event_bus.publish / subscribe / create_pending 打点，Chrome 真实复现）定位到**两个独立缺陷**，且**推翻了「背压丢包」的初始假设**（`qsizes` 全程为 0，256 队列驱逐从未发生）：

1. **`approval_request` 直播事件根本没发出（主因）**。`create_pending` 里落卡顺序是：建行 → `_pause_for_pending` → publish `approval_request`。而 `_pause_for_pending` 内含 ADR-028 D4 **H1 硬停**（`cancel_current_tick` 对当前 tick 发 cooperative cancel）。create_pending 跑在该 tick 协程内，cancel 一置位，本协程在紧随的 `await`（publish 那步）被 cancel 掉 → publish **永不执行**（`except Exception` 不接 `CancelledError`，故无报错日志，极隐蔽）。前端于是只剩两条可靠路径拿卡：连接时的 init 快照（REST 读 DB）和手动刷新 → 连接后新建的卡渲染成「已关闭」。

2. **event_bus 是 fire-and-forget、无重放（次因/连接空窗）**。`publish()` 遇 `if not subs: return` 直接丢。实测：mission 创建瞬间首个 `message`/`lifecycle_changed` 常在前端 EventSource 连上前（~3s 空窗）publish，`subs=0` → **永久丢弃**。silent 重连同理。

## Decision

### D1 · publish 顺序修正（主因）
`create_pending` 中把 **publish `approval_request` 挪到 `_pause_for_pending` 之前**（建行 → publish → pause）。落卡事件先确定性发出，再做「暂停 + H1 硬停当前 tick」。publish 收敛到 create_pending 这个**规范点**（覆盖所有调用方），退役 `request_approval` skill 里的重复 publish（原 v5 那处）。

### D2 · event_bus 每 channel 重放缓冲（次因 / 防御纵深）
`InProcessBus` 加 per-channel 有界 ring buffer（`_REPLAY_MAXLEN=256`，`_REPLAY_TTL_SEC=120s`）：
- `publish()` 无论有无订阅者都先入缓冲，再 fan-out。
- `subscribe()` 同锁内**先注册队列再快照缓冲**（原子，不漏不重），连上**立即重放**最近 TTL 内事件，再无缝续接实时。
- 无订阅者且缓冲全过期 → 回收，防泄漏。

覆盖：连接空窗 / 重连 / 无订阅者时 publish 的**所有**事件类型（不止审批卡），且**零延迟**（连上即补，不等心跳）。前端 handler 天然幂等（`message` 按 `m.id`、`approval_request` 按 `request_id`、`init` 合并去重）→ 重放安全，**纯后端改动，无需重建前端**。

## Considered alternatives
- **心跳（30s）重发 pending 快照**：纯后端、自愈，但最坏 30s 延迟 → 不满足「无延迟」。否。
- **前端 lifecycle→refetch**：即时但需重建前端 prod，且 lifecycle_changed 同样会在空窗丢。否（重放缓冲更通用）。
- **加大 256 队列 / 保护内容事件不被驱逐**：实测背压根本没发生（qsizes=0），是伪命题。否。
- **SSE 可恢复（Last-Event-ID + 事件 id）**：行业标准、重连秒恢复，但机制重（id 簿记/缓冲/重放）、单连接内空窗仍需另解、未来 PgNotify 多进程要重做。缓冲方案更轻且够用；留作后续演进。

## Consequences
- 审批卡（及所有实时内容）连接后**即时下发**，连接空窗/重连也能补齐，不再需要手刷。
- 每 channel 常驻一个 ≤256 事件、≤120s 的内存缓冲（单 uvicorn、mission 数有界，开销可忽略）。
- 教训：**cooperative cancel（H1）之后的代码是不可靠的**——关键副作用（publish/落库）必须放在置 cancel 信号**之前**。`except Exception` 不接 `CancelledError`，这类「协程被 cancel 吞掉后续 await」的 bug 无报错、极难查，只能靠给关键路径打点 + 真实浏览器复现定位。
- 残留：决卡后 `_trigger_tick_async` 无条件 spawn 与 auto-drain 会短暂产生多个 trigger 任务互相 cancel（噪声日志），会自愈、构建仍正确完成；可后续收敛 auto-drain 去重。
