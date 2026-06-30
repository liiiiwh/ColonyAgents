---
date: 2026-05-18
role: dev
task: M7 — AI Smoke Test（sandbox clone + run_once + LLM-as-judge）
related_task_id: M7
files_changed:
  - backend/app/services/project_test_runner.py   # 新建：clone_to_sandbox / cleanup_sandbox / run_smoke_test / _llm_judge
  - backend/app/skills_builtin/tester_skills.py   # 新建：project_run_test / sandbox_clone_project / sandbox_cleanup
  - backend/app/skills_builtin/__init__.py        # 注册 3 个 tester 工具
  - backend/app/skills_builtin/registry.py        # + 3 条 metadata（category='tester'）
  - backend/app/db/init_db.py                     # TesterAgent 绑 3 个工具；Supervisor 也绑 project_run_test
  - backend/tests/test_smoke_runner.py            # 新建：3 个测试
status: done

## 验证

- ✅ pytest 全套 119 passed（+ 3 M7 tests）
- ✅ backend 启动后：
  - 44 个内置 skill（custom 27 + builder 8 + installer 6 + tester 3）
  - Builder Project 3 个 worker 节点（builder_worker / installer / tester）已绑对应工具
- ✅ run_smoke_test：clone → start → run_once → stop → cleanup 流程完整跑通；judge 在测试环境降级 needs_review

## 已知遗留

- 实际 LLM judge 需 backend 进程内有可解析的 DEFAULT_AGENT_MODEL_ID + 该 provider 的解密 api_key（生产环境 OK；本地纯 sqlite 测试降级 needs_review）
- run_once 仍是 stub；M7 验证的是「测试框架本身可靠」，不是业务正确性
- BuilderAgent / TesterAgent 的 protocol_md 已硬编码"修改后 must call project_run_test"，但要 LLM 真的遵守，需要等真实 Builder chat 跑起来验证（Round-1 时人工试一下）

## 状态: 可测试 ✅
---

## 任务背景

按计划 M7：Builder AI 在结构性修改 Project 后能自动跑一轮 smoke test，并以 approval 卡片告知用户。

## M7 设计

- `project_test_runner.py`：
  - `clone_to_sandbox(db, project_id) -> Project`：复制 project + nodes 为新 project，slug=`sandbox-<orig>-<ts>`，status='draft' / runtime_status='stopped'
  - `cleanup_sandbox(db, sandbox_project_id)`：删除 sandbox project（cascade delete nodes / run_state / memory / schedules）
  - `run_smoke_test(db, project_id, scenario_text) -> dict`：核心入口
    1. validate_workflow（项目级 sanity check）
    2. clone_to_sandbox
    3. daemon.start(sandbox) → run_once → 拿到 RunState → daemon.stop(sandbox)
    4. cleanup_sandbox
    5. LLM judge：用 DEFAULT_AGENT_MODEL_ID 跑一个轻 prompt，输入 {scenario, run_count, current_step, last_error, validation_issues}，输出 JSON `{verdict: 'pass'|'fail'|'needs_review', reasoning, suggestions[]}`
- TesterAgent 工具：`project_run_test`（封装 run_smoke_test）+ `sandbox_clone_project` / `sandbox_cleanup`（低阶）
- BuilderAgent / TesterAgent 现都在 seed_builder_project 中创建，本步把 project_run_test 绑给 TesterAgent + Builder Supervisor

## M7 范围限定

- LLM judge 用现有 `resilient_llm` 模块；若 default model 解不出来则降级到 "needs_review" + 给原始数据
- 不真的执行业务 workflow（run_once 在 daemon 仍是 stub）；M7 阶段验证的是「结构 + 状态机 + 沙盒克隆」可靠性，不是真业务正确性
