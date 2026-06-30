---
date: 2026-05-17
role: dev
task: M3 — 项目级 Agent 记忆（project_agent_memory + memory_scope + clear_memory wiring）
related_task_id: M3
files_changed:
  - backend/app/models/project.py             # + ProjectAgentMemory
  - backend/app/db/base_all.py                # 注册
  - backend/app/services/session_service.py   # + get_project_memory / upsert_project_memory
  - backend/app/services/agent_service.py     # assemble_system_prompt_async 按 ctx.memory_scope 切换 branch / project
  - backend/app/services/project_daemon.py    # clear_memory 真正实现：删 project_agent_memory 全部行
  - backend/app/skills_builtin/context.py     # BuiltinToolContext + memory_scope='branch'/'project'
  - backend/app/schemas/project.py            # ProjectLifecycleAction + 'clear_memory'
  - backend/app/api/projects.py               # /lifecycle/clear_memory 接 daemon.clear_memory
  - backend/alembic/versions/022_project_agent_memory.py
  - frontend/types/project.ts                 # ProjectLifecycleAction + 'clear_memory'
  - frontend/app/admin/projects/[id]/page.tsx # RuntimeSection 加 "Clear Memory" 按钮 + Eraser icon
  - backend/tests/test_project_memory.py      # 4 个测试
status: done

## 验证

- ✅ alembic 022 升级 OK
- ✅ pytest 全套 116 passed（+ 4 M3 tests）
- ✅ frontend tsc 0 错
- ✅ memory_scope='project' 在 assemble_system_prompt 中正确读 ProjectAgentMemory
- ✅ `/lifecycle/clear_memory` 删除所有 project_agent_memory rows

## 已知遗留

- 真正使用 project memory 的 daemon 执行路径要到 M4 才打通（M3 只把基础设施铺好）
- s3_key 关联的 S3 对象在 clear_memory 时**不**真删；M4 后再补 S3 GC（避免误删现有数据）
- 修改 project 后的「自动 restart + 可选 clear_memory」逻辑在 M4 Builder Agent 工具里实现

## 状态: 可测试 ✅