# ADR-023 · 知识 / 记忆 / 存储 三能力边界重塑

- **状态**: Accepted（2026-06-22，grill 定稿）
- **分支**: `main`
- **相关**: ADR-018（mission-only）、ADR-022（Project→Mission 改名）

## 背景

用户反馈「知识库 / 物料库 / 对象存储这三个能力是不是都没用到，对象存储后台还报 500，要不要迭代」。grill 逐一对照代码后，三者其实是**三种不同状况**，不能一并「砍/留」：

- **对象存储**：后台 `/api/storage/files` 报 500 = `InvalidAccessKeyId`。根因：`docker-compose.yml` 把 `S3_ENDPOINT_URL` 覆盖到本地 `minio:9000`，但 **没覆盖 key/secret** → 漏用 `.env` 的远程 rustfs 凭据（`rustfsadmin`），本地 MinIO（`minioadmin/minioadmin`）拒绝。它**不是没用**：`write_artifact` 把每个 deliverable 都上传 S3（失败时静默降级为仅存 content，所以表面「能跑」掩盖了故障），`s3_*` skill 绑 15 agent。
- **知识库**：`knowledge_search` 是 super 强绑技能，种子协议**强制** Builder 提案前先查 KB 经验——设计上是核心一环。但一直 0 数据，真因：① `_ensure_*_kb` 在「系统无 enabled embedding 模型」时**静默跳过建库**（当前只配了 deepseek chat、无 embedding 模型）；② 缺 archive 闭环（mission 干完没人回写）；③ 无冷启动种子。后台 `/admin/knowledge` 列表 + 逐条删除**早已实现**（只是空）。
- **压缩记忆**：`mission_agent_memory` / `thread_agent_memories`，per-mission，超阈值自动压缩 + 每 tick 固定加载，`/mission/<slug>` Memory tab 已可查看/编辑/整体清空/版本回滚。**已齐全**。
- **物料库**：`material_lookup` 绑 15 agent、CRUD API + `/admin/materials` 录入/删除 UI 都齐，但**协议零驱动**（全代码搜不到一处教 agent 何时调），与知识库职能重叠，0 数据 = 实际死功能。

## 决策

1. **对象存储 — 保留 + 修配置**：在 `docker-compose.yml` backend `environment` 显式设 `S3_ACCESS_KEY_ID: minioadmin` / `S3_SECRET_ACCESS_KEY: minioadmin`，与 bundled MinIO 对齐；并加启动期 S3 健康检查 **fail-loud**（坏凭据/不可达要显式报，不再靠 `write_artifact` 静默降级掩盖）。
2. **知识库 — 保留 + per-super 共享 + 补闭环**：
   - KB 关联从 **per-mission（`knowledge_bases.mission_id` 1:1）改为 per-super 共享**（挂 super agent；同 super 的所有 mission 共用一份，知识跨实例累积）。需迁移 + 自动建库触发点从 `create_mission` 改到 super 创建。
   - 修 **embedding gate**：无 enabled embedding 模型时不再静默跳过，给明确引导（或降级建占位库），让「为什么没库」可见。
   - 补 **archive 闭环**：mission 收尾 `archive_to_knowledge` 沉淀经验 + 平台预置冷启动种子。
   - 后台列表/逐条删除沿用已有 UI。
3. **压缩记忆 — 维持现状**：per-mission、自动压缩、固定加载、Memory tab CRUD 已满足，不改。
4. **物料库 — 砍**：删 `materials` 表（迁移）+ `material_lookup`/`list_material_keys` skill（registry/metadata/factory/seed 解绑）+ `api/materials.py` + 前端 `/admin/materials` + 导航入口 + 相关 types/client。

## 后果

- 正面：三能力边界清晰——**对象存储=交付物存储（修好）/ 知识库=per-super 检索记忆（真转起来）/ 压缩记忆=per-mission 固定加载（不动）**；物料库这一与 KB 重叠的死功能删干净，减认知负担（合「绿地最优 / 不留无谓臃肿」）。
- 代价：KB schema 改 FK（mission→super）+ 自动建库触发点迁移；物料库删表迁移 + skill 解绑（LLM 工具面缩小，需同步种子协议）；docker-compose 凭据修。
- 不可逆点：删物料表 / KB FK 迁移 → 立此 ADR。
- 范围外：CONTEXT.md 第 34–37 行仍残留 `projects`/`project_agent_memory` 等旧名（ADR-022 文档收尾），与本 ADR 无关，另行清理。
