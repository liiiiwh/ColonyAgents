# HANDOFF · 续接清单（2026-06-22）

接续 grill(ADR-023/024)后的迭代实施。新会话从这里继续。

## 已完成并提交（S1–S9 + S7+）
- **S1** 对象存储修配置 + 启动健康检查 fail-loud（docker 验证 500→200）
- **S2** 审批流：读时合并 resolution+thread_key / force_human 去重 / 按 thread 过滤
- **S3** mission 页布局重构（左栏只 missions / 右栏 Threads tab / worker 只读+可读名 / 面包屑）
- **S4** super 自管调度 schedule_create/update/delete + 护栏（≤5条/≥5min/cron/token_guard）
- **S5** MCP 安装移出运营审批（super 协议：技术依赖缺失走 request_new_capability 不弹用户）
- **S6** 砍物料库（迁移 074 + registry 96→94）
- **S7** 知识库 per-super（迁移 075 super_agent_id + 回填 / get_kb_by_super / get_kb_by_project 先按 super 路由 / _ensure_super_kb 幂等 / embedding gate 告警 / archive 闭环引导）
- **S7+** onboarding 默认 embedding 后端（set-default-models 接受 embedding + default_embedding_model_id）+ spawn_mission 接 KB 触发 + _ensure_super_kb 用 _resolve_spec（支持 uuid / provider/model_id）
- **S8** 流式注释清理（后端 V7.2 已流式；前端/worker 流式实时性待动态观察）
- **S9** CONTEXT projects→mission 残留清理

测试：525+ passed，前端 tsc clean，迁移到 075。第一次 e2e 验证 S1–S6 通过（截图）。

## 环境就绪
- provider：deepseek + **volcengine**（base_url ark.cn-beijing.volces.com，含 doubao-embedding 系列）
- **default_embedding_model_id = `volcengine/doubao-embedding-large-text-250515`**（system_settings）
- KB 闭环已跑通：spawn mission → 自动建 `kb-super-*`（per-super）
- ⚠️ 用户在对话里贴过 volcengine API key 明文 → 提醒其轮换

## 待续接（按优先级）
1. **default 模型可见性（用户报）**：`default_supervisor/agent_model_id` 不在 system_settings（这个 DB 走 .env DEFAULT_*_MODEL_ID 的 env-install，没回写）→ 设置页看不到。修：env-install 时把 DEFAULT_*_MODEL_ID upsert 进 system_settings + 设置页加「默认模型」查看/编辑 UI（含 embedding，provider/model_id 形式展示）。
2. **onboarding InstallModal embedding 下拉 UI**：后端/API 已就绪（systemSettingsApi.setDefaultModels 已加 embedding 参数）；只差 InstallModal.tsx 的 state+加载(model_type=='embedding')+下拉+提示「不设知识库不可用」+ initialize 传 emb。
3. **apply_super_spec 的 KB 触发**：Builder 建**新 super** 第一个 mission 还没接 _ensure_super_kb（spawn 主路径已接）。
4. **10 场景 builder→super 多维评测**：完成率/通过率/调度完善度/持续运行/自学习(KB召回)/worker复用/builder反馈链路/状态自动暂停-继续；综合 >95 否则迭代优化协议；**优化后协议同步 init_db seed**。建议写脚本化评测 harness（API 驱动，非手动 playwright）。
5. **视频重做 + README 更新**（评测通过后）。

## 关键文件
- ADR：docs/adr/023（三能力）、024（super 会话/thread/UX）
- 词汇：CONTEXT.md「知识/记忆/存储」「Thread 三类」
- task 列表 #1–12（本会话建）
- 评测目标场景维度见用户原话（10 领域 + 95 分门槛 + 协议同步）

## docker
`docker compose -p colony-fresh -f docker-compose.yml -f /tmp/colony-fresh.override.yml up -d --build`（frontend 13022 / backend 19022 / minioadmin）
