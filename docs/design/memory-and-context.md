# 记忆与上下文系统

> ⚠️ **部分过时（ADR-018 mission-only 之后）**：`branch_agent_memory` / `session_branches` 表已删，"orchestrator session / branch" 概念退役。记忆现按 `(mission_id, thread_key, agent_node_name)` 存于 `thread_agent_memories`（线程级）+ `project_agent_memory`（mission 长期），压缩水位线在 `thread_compression_state`。当前权威见 [CONTEXT.md](../../CONTEXT.md) + [ADR-018](../adr/018-mission-only-model-and-iteration-routing.md) / [ADR-020](../adr/020-thread-key-scheme-and-mission-only-cleanup.md)。以下保留作历史参考（双轨记忆思路仍成立，"branch" 应读作 "thread"）。

## 双轨记忆

| 表 | 维度 | 用途 |
|---|---|---|
| `branch_agent_memory` | `(branch_id, agent_node_name)` | 本会话本分支的累积记忆；orchestrator session 主用 |
| `project_agent_memory` | `(project_id, agent_node_name)` | 项目跨 session 的长期记忆；持久化 daemon 主用 |

字段：`memory_md` (Text) / `compressed_message_count` (Int) / `s3_key` (Text) / `last_compressed_at` (TZ)

### 注入规则（`agent_service._render_system_prompt`）

| 场景 | 注入内容 |
|---|---|
| `memory_scope='project'`（daemon） | 仅 project memory |
| `memory_scope='branch'`（orchestrator） | **同时**注入 project memory（跨 session 累积）+ branch memory（本会话累积） |
| 两者皆空且 `domain_memory_md` 非空 | 注入 domain_memory_md 作为模板（仅首次） |

提示节标题：
- `## 项目长期记忆（跨 session 累积）`
- `## 当前分支记忆（本会话累积）`
- `## 领域初始记忆（模板）`

## Memory 写入路径

### 1. `memory_append` skill（**主用**）

结构化追加，不覆盖既有内容。参数：

| 参数 | 必填 | 用途 |
|---|---|---|
| `event` | ✅ | 动词开头，≤200 字 |
| `progress` | | 「N/M 步」或「项目=X 阶段=Y」 |
| `artifacts` | | `[{label, type, s3_url}]` —— meta only，不带 content |
| `decision` | | 关键决策 |
| `next_step` | | 下次 turn 启动时的续点 |
| `extra` | | 任意 dict（agent_id / install_id / 错误码等） |

scope 自动判定：ctx.memory_scope=='project' + ctx.project_id 走 project；否则走 branch。

写入格式（直接拼接到 memory.md 末尾）：

```markdown
### [2026-05-19 03:27:04 UTC] 方案选定: HN Daily Digest
- **progress**: 第 1/5 步完成
- **decision**: 走方案 A
- **next**: 调 skill_list_available 看 fetch_url
- **artifacts**:
  - 项目配置总结 (markdown) — `s3://...`
- **extra**: `{"target_slug":"hn-digest"}`
```

### 2. `memory_write` skill（**慎用**）

覆写式更新整个 `memory_md`。仅在需要修正错误记忆时使用。

### 3. 自动压缩写入

`maybe_compress_context` 触发后追加一个完整段落：

```markdown
---
## 压缩段 #N（2026-05-19 03:00 ~ 2026-05-19 03:30，K 条消息）
<!-- 该段为独立摘要，覆盖上述时间窗口的对话，不引用其他段落 -->

## 概要(<= 100 字)
...

## 时间线 / ## 决策 / ## 工具调用 / ## 卡片 / ## 产物
...

<!-- end 压缩段 #N -->
```

## 异步上下文压缩

### 触发判定

**仅看未压缩的 user↔assistant 对话**：

```python
total = sum(_estimate_tokens(m.content) for m in uncompressed_msgs if m.role in ('user','assistant'))
if total >= project.context_compression_threshold:
    -> 派发后台任务
```

**不计入触发判定**：
- supervisor system prompt 静态部分（soul / protocol / skill instructions）
- 已存在的 `memory_md`
- `branch.workspace` snapshot

**理由**：若把 memory 算进阈值，memory 越长触发越频繁，越压越多 → 死循环。

### 阈值

- 默认 `300_000` token（用 `len(text)` 估算，对中文 1 char ≈ 1 token 偏保守）
- 可在 `core/config.py::DEFAULT_CONTEXT_COMPRESSION_THRESHOLD` / `.env` 全局覆写
- 每个 project 在 `projects.context_compression_threshold` 字段独立覆写

### 派发流程

```
api/sessions.py
   │
   ├─ schedule_compression_if_needed(branch_id, "supervisor", threshold)
   │     │
   │     ├─ 进程内 set: branch_id ∈ _COMPRESSION_IN_PROGRESS_LOCAL? → 跳过
   │     │
   │     ├─ DB CAS: UPDATE session_branches SET compression_in_progress=TRUE
   │     │           WHERE id=? AND compression_in_progress=FALSE RETURNING id
   │     │         → rowcount=0 → 跳过（已有任务在跑）
   │     │
   │     ├─ asyncio.create_task(_runner())  ← 强引用存进 _COMPRESSION_BG_TASKS
   │     │
   │     └─ 返回（< 10ms）
   │
   └─ 本轮 SSE 继续，prior_messages 加载未压缩消息全量 snapshot
```

### Worker（`_runner`）

```python
async with AsyncSessionLocal() as db:
    branch = await get_branch(db, branch_id)
    await maybe_compress_context(db, branch, "supervisor", threshold)
finally:
    # 清进程内 set + DB flag
    _COMPRESSION_IN_PROGRESS_LOCAL.discard(branch_id)
    UPDATE session_branches SET compression_in_progress=FALSE WHERE id=?
```

### 水位线 `compressed_up_to_at`

压缩成功时 atomically 写入 `compressible[-1].created_at`：所有 `created_at <= 水位线` 的消息已被压缩。

- 单一真相源；任何 reader（前端、SQL 排查、未来 prompt 构造器）都可读
- 与 `Message.is_compressed=True` 标记并存（双轨），便于按消息粒度查询

### 并发保证

| 保护点 | 失败时表现 |
|---|---|
| 进程内 `set` | 同一进程下连发两次请求只派发 1 个任务 |
| DB CAS（`WHERE compression_in_progress = FALSE`） | 跨进程也能保证不并行（如未来多 worker） |
| finally 清理 | 任务异常退出时仍能复位；SIGKILL 残留需重启或人工 reconcile |

## Supervisor 每次看到什么（context assembly）

构造顺序：

1. **静态层**（来自 agent + 绑定 skill）
   - `soul_md` + `protocol_md` + 所有绑定的 instruction skill content_md

2. **记忆层**（来自 DB）
   - 「项目长期记忆」（若 ctx.project_id 存在且 ProjectAgentMemory 有内容）
   - 「当前分支记忆」（若 ctx.branch_id 存在且 BranchAgentMemory 有内容）

3. **快照层**（动态拼装）
   - `_build_project_nodes_snapshot`：节点清单 + category
   - `_build_branch_status_snapshot`：每节点状态徽章 + artifacts **meta**（label/type/s3_url，**不含 content**）+ state keys + value preview

4. **对话历史**（来自 messages 表）
   - 所有 `is_compressed=False` 且 `role ∈ {user, assistant}` 的消息按 `created_at` 升序
   - **历史 user 消息携带的 attachments（meta.attachments）会被重建为 LangChain 多模态 HumanMessage**：image 块走 `{type:'image_url', image_url:{url}}`、file/text 块走文本段。vision LLM 在后续 turn 仍能"看到"之前上传过的图。

5. **本轮 user 消息**（来自请求 payload）
   - 由 `_build_user_message_payload` 构造；多模态 parts 列表替换 prior_messages 末位的纯文本 HumanMessage

### 各层占位估算（参考）

| 层 | 典型大小 |
|---|---|
| 静态层（Builder Super） | ~10k 字符 |
| 记忆层 | 0 ~ 数十 k 字符（取决于使用时长） |
| 项目快照 + 分支快照 | < 5k 字符 |
| 对话历史 | 0 ~ threshold 字符 |

加起来即使全部满载也远小于 1M token 窗口；阈值 300k 给的是「对话部分」的保守上限。

## 段落隔离与防污染

LLM 摘要 prompt 显式规定：

> 严格输入隔离原则（防 memory 互相污染）：
> - 只能根据**我现在给你的这批消息**做摘要——不要引用任何「之前的记忆 / 上一次压缩段」，因为你完全看不到那些
> - 不要编造没有出现在本批消息里的对话、工具调用、产物、用户决策
> - 不要尝试与「未提供」的上下文做连续性推断
> - 摘要本身是自包含段落，未来会被原样拼接到 memory 末尾

技术上 `_llm_summarize` 也只把本批 `compressible` 消息序列化成 JSON 喂给 LLM——**不传 memory_md、不传其他 segment**，源头杜绝交叉污染。

`_build_summarize_payload` 还会**缩减 meta.attachments**：

- `data:image/...;base64,...` data URI → `<data URI data:image/png;base64, ~N bytes base64>`
- URL → 保留前 200 字符
- 长文本 → 头 100 + 中略 + 尾 50

防止图片 base64（动辄数十 KB～MB）撑爆 summarizer LLM 的输入。摘要 prompt 显式要求保留「`## 用户附件` section：列出 type / name / media_type / content_ref」，让 Supervisor 在压缩后仍能知道「用户在 T 上传过 foo.png」——但**不**让 summarizer LLM 真正"看到"图像内容（那需要再次走多模态 LLM，不适合作为压缩任务）。

每段写入时带 HTML 注释边界：

```markdown
<!-- 该段为独立摘要，覆盖上述时间窗口的对话，不引用其他段落 -->
...
<!-- end 压缩段 #N -->
```

## 相关代码索引

| 关注点 | 入口 |
|---|---|
| 触发 | `app/api/sessions.py::chat`（line ~564） |
| 派发 | `app/services/session_service.py::schedule_compression_if_needed` |
| 工作 | `app/services/session_service.py::maybe_compress_context` |
| LLM 摘要 | `app/services/session_service.py::_llm_summarize` |
| 字符估算 | `app/services/session_service.py::_estimate_dialogue_tokens` |
| memory_append | `app/skills_builtin/memory_skills.py::memory_append_tool` |
| 注入 prompt | `app/services/agent_service.py::_render_system_prompt` |
| 水位线列 | `app/models/session.py::SessionBranch.compressed_up_to_at` |
| Alembic 迁移 | `alembic/versions/025_branch_compression_marker.py` |
