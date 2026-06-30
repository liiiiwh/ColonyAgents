# Colony · 文档索引

> 项目级基础规范在 `SPEC.md`。本目录维护**详细设计 + API 字段约定 + 数据模型细节**。

## 设计文档（`design/`）

| 文档 | 内容 |
|---|---|
| [architecture.md](design/architecture.md) | 两层架构（Meta / Worker）+ 模块边界 + 数据流 |
| [memory-and-context.md](design/memory-and-context.md) | 双轨记忆（branch + project）/ 异步压缩 / 上下文组装 / Supervisor 每次看到什么 |
| [builder-project.md](design/builder-project.md) | Builder Project 4 个内置 Agent 的职责、协议、Skill 绑定与编排时序 |

## API 文档（`api/`）

| 文档 | 内容 |
|---|---|
| [orchestrator.md](api/orchestrator.md) | `/api/orchestrator/*` Builder Chat 后端契约 |
| [projects.md](api/projects.md) | Project / lifecycle / schedule API |

## 阅读顺序建议

新成员：`architecture.md` → `builder-project.md` → `memory-and-context.md` → API 文档
排查问题：直接看相关模块的 design 文档 + `devlogs/` 最新条目

## 不在这里维护的内容

- **项目定位 / 技术栈 / 全局约束** → 见 `SPEC.md`
- **历史交付记录 / 阶段性变更** → 见 `devlogs/` + `CHANGELOG.md`
- **AI 工作流规范** → 见 `AGENTS.md`
- **内置 Skill 列表与字段** → 直接看 `backend/app/skills_builtin/registry.py::BUILTIN_SKILL_METADATA`（代码即文档）
