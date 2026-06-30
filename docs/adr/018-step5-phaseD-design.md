# ADR-018 Step 5 · Phase D 设计 — main 线程按 mission 唯一

**Status**: Designed (2026-06-18), 待执行(独立专项)
**前置**: B.1/B.2 完成。**解锁**: B.2-main、B.3、C 的 main 线程改键。

## 问题

`thread_key_for` 把所有 `thread_kind ∈ {NULL, super_main_runtime, legacy, daemon}` 的 branch 都折叠成
`'main'`。但一个 mission 下可有**多条** branch 都 →`'main'`:
- **orchestrator(builder chat)会话**:每条是独立 build 对话,`create_session` 给的 `thread_kind=NULL`、
  `thread_id=uuid4`(**已唯一**),但被折叠丢弃 → 多 build 撞同一 `'main'`。
- **rollback 版本分支**:`rollback_to_node` 建的新 branch `thread_kind=NULL`、`thread_id=uuid4`(唯一),同样折叠。

后果:压缩记忆(B.2)/压缩状态 CAS(B.3,按 branch 原子 `UPDATE`)/消息读(C)无法按 `(mission, thread_key)`
改键 —— 会跨 build 串记忆 / 串压缩状态(已被 `test_memory_read_write_per_branch_isolation` 钉死)。

## 关键洞察

**唯一性已经存在**:每条 orchestrator/rollback branch 都已有唯一 `thread_id`。撞车纯粹是 `thread_key_for`
把它折叠成 `'main'` 造成的。只有 daemon 主线程(`thread_kind='super_main_runtime'`,每 mission 恰一条)
**应该**是 `'main'`(用户可见主流)。

## 决策:轻量改键(非 project-per-chat)

保留 orchestrator 会话为 builder project 下的 session;**不**给每条 build 建独立 Project。只改键:

```
thread_key_for(thread_kind, thread_id):
  worker_health          → 'health'
  super_worker_thread     → thread_id          # 已唯一(super-X-worker-Y)
  super_main_runtime      → 'main'              # ★ 唯一的 mission 主流,保持
  else (NULL/builder_chat/rollback/legacy)
                          → thread_id           # ★ 改:不再折叠成 'main',用唯一 thread_id
```

- daemon 主线程(`super_main_runtime`)仍 `'main'` —— 每 mission 一条,无撞车,B/C 改键对常规 super 直接可用。
- orchestrator / rollback / 其它 → 各自 `thread_id` → 互相隔离 → B.2-main 的 `memory_skills` 改读可放行、
  B.3 压缩状态可按 thread 改键、C 消息读可按 thread。

**与 D3 provenance 的关系**:本轻量方案解锁建表退役(Step 5 的目标),但 `built_by_mission_id` 仍指 builder
project(单例)。"escalation 路由切 provenance 到具体 build 对话"需要 build 各成独立 mission(完整 D3),
属**可选的后续**,不阻塞建表退役。迁移期 escalation 继续走 `origin_session_id` 链(工作正常)。

## 执行步骤(每步 TDD + docker 验证)

1. **`thread_key_for` 改 else 分支** → 返回 `thread_id`(NULL 时回退 `'main'` 兜底空 thread_id)。
   单测:orchestrator 两 branch(不同 thread_id)→ 不同 thread_key;daemon super_main_runtime → `'main'`。
2. **迁移 066 · 回填**:对受影响的历史消息重算 `thread_key`:
   ```sql
   UPDATE messages m SET thread_key = b.thread_id
     FROM session_branches b
    WHERE m.branch_id = b.id
      AND (b.thread_kind IS NULL OR b.thread_kind NOT IN
           ('super_main_runtime','worker_health','super_worker_thread'))
      AND m.thread_key = 'main';
   ```
   同步回填 `thread_agent_memories.thread_key`(同条件 join)。**注意**:daemon 主线程 messages 不动。
3. **放行 B.2-main**:`memory_skills` 的 `get_branch_memory` → `get_thread_memory_for_branch`(B.2 已留的 TODO),
   隔离测试现在应自然通过(两 branch 不同 thread_key)。
4. **B.3**:`ThreadCompressionState(mission_id, thread_key)` + CAS 改键 + waterline + circuit-breaker;
   `maybe_compress_context` 消息选择改 `(mission_id, thread_key)`(并入 C)。
5. **C**:5 处 `messages.branch_id` 读 → `list_thread_messages`;`append_message` 收 `(mission_id, thread_key)`。

## 风险

- **改键是全局双写语义变更**:步骤 1+2 必须原子(改 `thread_key_for` 的同时回填历史),否则一条 build 对话的
  新旧消息分属 `thread_id` 与 `'main'` 两键 → 历史割裂。先在 docker 全量验证再上云。
- **rollback 版本分支语义**:rollback 建的新 branch 现在拿独立 thread_key → 与父分支记忆隔离。
  这符合 `test_memory_read_write_per_branch_isolation` 的隔离预期;但若产品上 rollback 应"继承父对话记忆",
  需让 `rollback_to_node` 复用父 branch 的 thread_id(而非新 uuid4)。**执行前需产品确认 rollback 语义**。
- daemon 主线程判定依赖 `thread_kind='super_main_runtime'` 准确;legacy NULL 主线程数据需确认无误判。

## 不做

完整 project-per-chat(每 build 一个 Project)—— 过重,且建表退役不需要。`built_by_mission_id` 的细粒度
escalation 路由留作可选后续。
