# ADR-021 · 后端文件布局重组（去遗留命名 + 分域）

- **状态**: Accepted（2026-06-22，grill 定稿）
- **分支**: `main`
- **相关**: ADR-018（mission-only）、ADR-020（thread_key/收尾）

## 背景

ADR-018 把运行时收口到 mission-only，但**文件名/目录仍是迁移前结构**，file-tree 可读性差：
- `services/session_service.py`（1007 LOC 巨石，名为 session 实则做 messages/workspace/memory/compression）、`models/session.py`、`schemas/session.py` —— "session" 概念已退役，名字误导。
- `skills_builtin/` 31 个扁平 `*_skills.py`，无分组。
- 版本后缀残留：`observe_v3.py`、`builder_v3_skills.py`。
- `backend/scripts/legacy/` 一批一次性历史脚本（lingyou seed、protocol patch、probe）。

v1 未发布 → **无需向后兼容**，可直接改名/移动/删除（不留 shim）。

## 决策

纯结构重组（**零行为变更**），分片执行、每片全套测试绿后提交：

1. **拆 `session_service.py` → 4 个按域服务**：
   - `messaging_service.py` — append_message / list_thread_messages
   - `workspace_service.py` — write_artifact / write_artifacts_batch / _workspace_key
   - `memory_service.py` — thread/project 记忆 upsert+get
   - `compression_service.py` — maybe_compress_context / schedule / config / 水位 / summarize / token 估算
   `session_service.py` 删除（不留 re-export shim）。
2. **数据层改名**：`models/session.py → models/message.py`（Message + ThreadAgentMemory + ThreadCompressionState）；`schemas/session.py → schemas/message.py`。`db/session.py` **保留**（标准 SQLAlchemy session，非遗留）。
3. **`skills_builtin/` 分域子包**（文件逻辑不动，仅移位 + 改 import/registry）：`builder/` `super/` `worker_io/` `knowledge/` `channel/` `quality/` `llm/`；`registry.py`/`context.py`/`skill_scope.py`/`__init__.py` 留顶层。
4. **去版本后缀**：`observe_v3.py → observe.py`；`builder_v3_skills.py` 并入 `builder/`。
5. **删冗余**：`backend/scripts/legacy/`（一次性历史脚本）。

## 后果
- 正面：file-tree 一眼可读，名字与 mission/thread 域一致；巨石拆开后各服务可单独测/读。
- 代价：高 fan-in 改名（session* 各 ~28 import）+ 31 文件移位 + registry 重连，churn 大；靠分片 + 全套测试兜底。
- 不可逆点：模块路径变动（import 大面积改）——故立此 ADR。
- **执行顺序（低→高风险）**：① 删 legacy ② 去版本 ③ models/schemas 改名 ④ session_service 4 拆 ⑤ skills 分域子包。每片独立提交，中途不留 broken。

## 落地（2026-06-22 全部完成）
全 5 片均已分片提交、每片 513 passed：
- ④ `session_service.py`（1007 LOC）→ `messaging_service` / `workspace_service` / `memory_service` / `compression_service`，删原文件无 shim，~25 importer 改指向新域服务。
- ⑤ `skills_builtin/` 27 模块 → 7 子包：`builder/`（含 `builder_lifecycle_skills`，原 `builder_v3_skills` 去版本）`super/` `worker_io/` `knowledge/` `channel/` `quality/` `llm/`；`registry.py`/`context.py`/`skill_scope.py`/`__init__.py` 留顶层；全量 import 路径 + registry 重连。
