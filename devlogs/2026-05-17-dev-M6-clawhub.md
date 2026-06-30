---
date: 2026-05-17
role: dev
task: M6 — ClawHub 远程 Skill 仓库集成（HTTP client + 安装器 + Builder 工具）
related_task_id: M6
files_changed:
  - backend/app/core/config.py                      # + CLAWHUB_TOKEN / BASE_URL / INSTALL_DIR
  - backend/app/models/skill.py                     # + RemoteSkillInstall 表
  - backend/app/db/base_all.py                      # 注册
  - backend/app/services/clawhub_client.py          # 新建：httpx async + 429 重试 + search/get_skill/security/download
  - backend/app/services/remote_skill_installer.py  # 新建：inspect/install/uninstall/list_installed + runtime kind 检测 + mirror skill
  - backend/app/skills_builtin/clawhub_skills.py    # 新建：6 个工具（search/inspect/install/uninstall/list_installed/remote_skill_invoke stub）
  - backend/app/skills_builtin/__init__.py          # 注册
  - backend/app/skills_builtin/registry.py          # + 6 条 metadata
  - backend/app/db/init_db.py                       # InstallerAgent 自动绑 clawhub_install/inspect/list/uninstall/search/request_approval
  - backend/app/api/admin_clawhub.py                # 新建：/api/admin/clawhub/{search,inspect,install,installed,install/{id}}
  - backend/app/main.py                             # 挂 router
  - backend/alembic/versions/024_remote_skill_install.py
  - frontend/types/clawhub.ts                       # 新建
  - frontend/lib/api/clawhub.ts                     # 新建
  - frontend/app/admin/skills/page.tsx              # + ClawhubBrowser（搜索/安装/已安装/卸载）
status: done

## 验证

- ✅ alembic 024 升级 OK
- ✅ 116 tests pass, frontend tsc 0 错
- ✅ E2E（真连 https://clawhub.ai）：
  - `/api/admin/clawhub/search?query=fetch` → 5 个 hit（含 "fetch" 自身）
  - `/api/admin/clawhub/inspect?slug=fetch` → version=1.0.0, blocked=false, high_risk=[]
  - `POST /api/admin/clawhub/install {slug:'fetch'}` → ok=true, kind=static-instruction, entry=SKILL.md, install_dir=/colony/runtime/skills/fetch@1.0.0/, install_id, local_skill_id
  - 解压目录确实生成；mirror skill 写入 skills 表（slug='clawhub-fetch-1.0.0', category='installer'）
  - `DELETE /api/admin/clawhub/install/{id}` → HTTP 204 + 删本地目录 + 删 mirror skill

## 已知遗留

- python / node / nextjs / mcp-server kind 的实际 invoke 留到 M7+（M6 仅 stub）
- 高危 capability tags 闸口已实现（needs_approval），但 colony M6 也不真跑可执行代码所以"危险性"主要在 skill 的 SKILL.md 中如果包含恶意 prompt — 这是 Builder/InstallerAgent 的判断范围

## 状态: 可测试 ✅
---

## 任务背景

按计划 M6：
- 接 `https://clawhub.ai/api/v1` 真实 API
- 后端 `clawhub_client` HTTP 薄封 + 安全前置 + 限流处理
- `remote_skill_installer` 解析 manifest 判 kind (python / node / nextjs / mcp / static)
  + 装依赖 + 生成 wrapper + 写 DB 行
- Builder / Installer 工具：clawhub_search / inspect / install / uninstall / list_installed
- 管理后台 Skill 页加 ClawHub Tab

## M6 范围限定

- 不真的运行非 Python skill（node/mcp 需要 child process orchestration，规模过大）；M6 只完成元数据安装：
  - download zip / tgz 到 `runtime/skills/{slug}@{version}/`
  - 解析 manifest 判 kind
  - 创建 DB 行（runtime_kind = python / node / mcp / static-instruction）
  - 把 ClawHub skill 反射成本地 Skill 行（`skills` 表，is_builtin=False, builtin_ref=remote_install_id），供 Agent 绑定
- Python wrapper 仅 stub（log 一行 + 返回 "not yet wired" 给 LangChain），M7 起逐步完善
- 沙箱 / 高危 capability approval：本 M6 实现 capability check + Builder protocol 提示；真正 approval 在 Builder AI 调用前后端时由 InstallerAgent 弹

## 改动文件清单

- backend/app/services/clawhub_client.py        # 新建：search / packages_search / packages / security_summary / download
- backend/app/services/remote_skill_installer.py  # 新建：install / inspect / list_installed / uninstall + runtime kind 检测
- backend/app/models/skill.py                   # + RemoteSkillInstall 表
- backend/app/db/base_all.py                    # 注册
- backend/app/schemas/remote_skill.py           # 新建 schemas
- backend/app/api/admin_skills.py               # 新建：/api/admin/clawhub/* (search/inspect/install/list_installed/uninstall)
- backend/app/skills_builtin/clawhub_skills.py  # 新建 LangChain 工具：clawhub_search/inspect/install/uninstall/list_installed
- backend/app/skills_builtin/__init__.py        # 注册
- backend/app/skills_builtin/registry.py        # + metadata
- backend/alembic/versions/024_remote_skill_install.py
- frontend/types/clawhub.ts
- frontend/lib/api/clawhub.ts
- frontend/app/admin/skills/page.tsx            # + ClawHub Tab（search + install）
- tests/test_clawhub.py
