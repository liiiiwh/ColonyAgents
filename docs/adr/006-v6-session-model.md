# ADR-006 · v6 Session Model · Drop branch/scope split

**Status**: Accepted (2026-05-28)
**Supersedes**: v3 session_branches multi-branch + sessions.scope split

## Context

v3 模型为了支持「rewind 重跑」+「LangGraph 并行投机」+「daemon 内部 reasoning vs 用户对话隔离」引入了：

```
Project
└── Session (scope ∈ {daemon, orchestrator, super_main_runtime})
    └── SessionBranch[N] (branch_number, parent_branch_id, is_current)
        └── Message[N]
```

实战副作用：
- `_create_daemon_run_branch` 每次 tick 新建 branch，一天可膨胀到 281 条
- `is_current` 字段需要在多 schedule 间反复 flip，bug 高发（v3 注释自己承认实测一天 281 条）
- UI 看到「2 个 daemon」是 fork branch 残留，用户困惑「为什么有重复」
- 跨 branch memory 又走 project_agent_memory 全局共享 → branch 实际并没隔离任何持久状态，只是隔离了消息流，但 super 想读自己的 reasoning history 反而要按 branch 切

## Decision

```
Mission (= Project row, 不动)
├── Sessions[N]                                       # 每个 session = 1 个长跑 daemon
│   ├── Messages (linear)                             # user + assistant + artifact + tool_output 同一根
│   ├── SessionAgentMemory                            # 任务总结/统计 (项目级仍然 project_agent_memory)
│   └── Activities (agent_activities tree, Phase I)   # 调度/调用/思考元数据
└── KB (3-tier scope union, Phase C)                  # 经验/规则
```

关键不变式：
- **每个 Session 恰好 1 个 active Thread**（仍复用 session_branches 表，但 `branch_number/parent_branch_id/is_current` 字段 **deprecated**，由 ORM 保留默认值）
- **没有 daemon-scope 和 super_main_runtime 的区别** —— super 内部 reasoning 直接写主 thread，meta.source 区分用户可见 vs 系统内部
- **artifact / tool_output 也是 message**（meta.kind 标识），用户可在对话流看到
- **per-tick state** 全部走 `agent_activities` 表，不再开 SessionBranch

## Rollout · 不破坏运行的 daemon

**Phase L.1（不动 DB schema）**：
- `project_daemon.run_once`: 不再调用 `_get_or_create_task_branch`；直接用 `_ensure_super_session` 返回的 main branch 作为 ctx 的 session_id / branch_id
- 移除 final_text mirror（已在同一个 branch 上写了）
- `_create_daemon_run_branch / _ensure_daemon_session / _get_or_create_task_branch` 标 deprecated 但保留（外部脚本可能调用）
- `observeV3.superThreads` GROUP BY session_id：UI 上每个 session 只显示 1 行，多 branch 合并消息数
- 前端 Sessions 侧栏：可点击切换、可删除（除当前活跃 session）

**Phase L.2（可选 follow-up）**：
- alembic migration: drop `session_branches.{branch_number, parent_branch_id, is_current}` 字段
- 把 session_branches 重命名为 session_threads（1 session : 1 thread）
- 删 `_get_or_create_task_branch / _create_daemon_run_branch` 代码
- 前端老 branch viewer 路径删除

## Consequences

**+**：
- super 下次 tick 读到真实用户对话历史（而不是自己上次 reasoning 的乱七八糟思维链）
- UI Sessions = 真 sessions，不再有「2 个 daemon」幻觉
- 删除 session 语义清楚（删 mission 内一段对话 + 子目标 + 该 session 的 memory）
- artifact 显示位置自然（消息流时间序）

**-**：
- 老 branch 数据不会自动迁移；继续躺在 DB（无害，UI 不显示）
- daemon LLM 内部消息（如果将来想暴露 step 跟踪）需要走 agent_activities 而非 session message
- 外部脚本/导出工具如果按 branch_number 读，需要改成读 session_id

**回退方案**：将 `_ensure_super_session` 返回的 branch_id 重新换回 `_get_or_create_task_branch`，daemon-scope 老逻辑立刻恢复。Phase L.2 才会真正破坏向下兼容。
