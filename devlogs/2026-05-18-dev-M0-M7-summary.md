---
date: 2026-05-18
role: dev
task: M0-M7 全部落地 + Round-1/Round-2 稳定性验证总结
related_task_id: M0-M7
files_changed:
  - SPEC.md（七章重写 + 变更记录追加 M1-M7）
  - 已在各 milestone 自己的 devlog 详列
status: done
---

## 一句话总结

按已批准计划，从 toystory-agents fork 起步，**8 个 Milestone（M0-M7）** 已全部交付：
- 后端 122 个路由 / 119 pytest 全过 / 24 个 alembic 迁移到 head `024_remote_skill_install`
- 前端 0 个 tsc 错误 / 11+ 个页面 200 / Orchestrator + Observation + ClawHub Tab 全部可用
- Builder Project 自带 4 个 Agent（Builder Supervisor / Builder Worker / Installer Agent / Tester Agent）+ 44 个 builtin skill（含 8 builder + 6 installer + 3 tester + 27 通用）
- 真实远程 ClawHub `search/inspect/install/uninstall` 通

## 各 Milestone 已完成清单（含 devlog 链接）

| M | 主题 | 关键交付 | devlog |
|---|------|---------|--------|
| **M0** | Fork baseline | 拷贝 toystory-agents → colony；重命名；去多用户 ACL；agents/skills 加 category；alembic 019_colony_baseline | `2026-05-17-dev-M0-fork-baseline.md` |
| **M1** | Project lifecycle | runtime_status / project_run_state / start/stop/restart / heartbeat sweeper / boot reconcile；admin RuntimeSection | `2026-05-17-dev-M1-project-lifecycle.md` |
| **M2** | Scheduler | APScheduler + project_schedule + CRUD + webhook fire；admin SchedulesSection | `2026-05-17-dev-M2-scheduler.md` |
| **M3** | Project memory | project_agent_memory + memory_scope='project' + clear_memory；RuntimeSection Clear Memory 按钮 | `2026-05-17-dev-M3-project-memory.md` |
| **M4** | Orchestrator + Builder seed | sessions.scope + /api/orchestrator/* + seed Builder Project + 8 个 builder_skills + /orchestrator 页面 | `2026-05-17-dev-M4-orchestrator.md` |
| **M5** | Observation page | /observe/[slug] 只读 + 5 按钮 + 5s 轮询；/p/[slug] redirect | `2026-05-17-dev-M5-observation.md` |
| **M6** | ClawHub | HTTP client + remote_skill_installer + runtime kind 检测 + 6 个 clawhub_skills + admin/skills ClawHub Tab | `2026-05-17-dev-M6-clawhub.md` |
| **M7** | AI Smoke Test | project_test_runner + sandbox clone + LLM judge + 3 个 tester_skills | `2026-05-18-dev-M7-smoke-test.md` |

## Round-1 稳定性验证（结果摘要）

- ✅ pytest 119 passed, 2 skipped
- ✅ frontend tsc 0 错
- ✅ 6 个核心 API endpoint 全 200：`/api/health, /agents, /projects, /skills, /providers, /orchestrator/projects`
- ✅ 10 个前端页面全 200：`/, /login, /projects, /orchestrator, /admin, /admin/agents, /admin/projects, /admin/skills, /observe/builder, /p/builder`
- ✅ 完整 lifecycle e2e：create project → start → schedule(event) → event fire (fire_count=1) → clear_memory → restart → stop → delete
- ✅ ClawHub install/uninstall roundtrip（slug='fetch' 真连 clawhub.ai）

## Round-2 稳定性验证（重启 + reconcile + rehydrate）

- ✅ 创建 3 个 project 都 start + 加 cron schedule
- ✅ backend 重启后：
  - reconcile 检测到 3 个项目心跳新鲜 → 保留 running 状态（不误标 error）
  - scheduler rehydrate 3 个 cron jobs from DB
  - heartbeat-sweeper 重新启动
- ✅ 清理无残留

## 已知遗留（不影响 M0-M7 demo，留给后续）

1. **Real LLM judge 在 sqlite 测试场景**降级为 needs_review；生产环境（远程 PG + Provider api_key 已解密）正常工作
2. **run_once 仍是 stub**：M2/M3/M7 都基于此假设；真正业务执行要 daemon 接入 chat-like Agent loop（不在 M7 范围）
3. **ClawHub non-Python skill** 安装后只下载 + 解析 manifest + 写 DB；实际执行（node / nextjs / mcp）M7+
4. **Builder AI 是否遵守 protocol_md** 中"修改后 must call project_run_test"：需要真实 chat 触发验证（人工测一下）
5. **多 worker 部署**：APScheduler in-process + heartbeat 都会重复触发；MVP 单进程 OK
6. **observation page 实时事件 SSE**：M7 之后接入 daemon broadcast hub 才能从轮询升级为长连接

## 推荐人工验证步骤

1. 浏览器打开 http://localhost:3022/login（admin / admin123）
2. **/orchestrator**：Builder Project 出现；目标 project 切换器；试发"列一下你现在能调的工具"→ Builder Supervisor 应能罗列 builder skills
3. **/admin/projects**：能看到 Colony Builder + R1/R2 残留（应已清）；点进 builder 项目 → RuntimeSection 启停；SchedulesSection 新建 cron
4. **/admin/skills**：底部 ClawhubBrowser 搜索 "fetch" → 安装 → 已安装列表出现 → 卸载
5. **/observe/builder**：状态徽章 + 5 按钮 + 消息列表（暂空）

## 启动命令

```bash
# 一次性：基础设施
docker compose -f docker-compose.infra.yml up -d  # 远程 PG/S3 已配，本地用 .env 指向远端

# 后端 + 前端（监听 9022 / 3022）
bash scripts/dev-backend.sh
bash scripts/dev-frontend.sh
```

## 状态: 可测试 ✅ — M0~M7 全部就绪
