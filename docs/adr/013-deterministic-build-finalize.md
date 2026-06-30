# ADR-013 · 构建确定性收尾（工厂可靠性：代码强制收尾，不靠 LLM 记得）

**Status**: Accepted (2026-06-06)
**Builds on**: ADR-010（就绪）、ADR-011/012（首跑/交接）

## Context

多次 E2E 暴露：Builder 工厂靠一条**超长 LLM 协议**让模型记得走完所有步骤（注册 MCP→设
startup_command→mcp_ensure_ready→activate_super_first_run→提案）。模型不稳定地**跑到一半就停**，
留下半成品壳：super 建了、但 MCP 没就绪、没激活、没「进入」按钮。这是工厂**可靠性**问题，
与 ADR-010/011/012 的功能正确性无关——根因是「关键收尾步骤依赖 LLM 主动调用」。

## Decision

把收尾从「LLM 记得调」改为「**代码强制执行**」。

### R1 · 确定性 finalize（`build_finalizer.finalize_super_build`）
对一个 super 项目幂等地：
1. `ensure_ready` 相关本地 http MCP（绑到项目 agent 的；没有则回退到系统受管的本地 MCP）→
   扫码/密钥卡落到**本项目**会话；
2. `_ensure_daemon_session` + `start(kickoff=True)` 激活 super 首跑；
3. 在 Builder 会话写 `super_activated` 消息 → 前端渲「进入 super →」按钮（新标签）。
- **幂等**：已存在本项目的 `super_activated` 消息 → 跳过；卡片按标题去重，不重复发。

### R2 · Builder tick 后自动调用（`maybe_finalize_after_builder_tick`）
- 信号：`project_create` 会把 **Builder 会话的 `target_project_id`** 指向新建项目。
- 钩子：`project_daemon.run_once` 正常结束（无 err）后，若当前是 **Builder 项目**的 tick →
  读其会话 `target_project_id` → `finalize_super_build`。
- 于是无论 LLM 有没有记得收尾，**每次 Builder tick 结束代码都把它建的项目收尾到位**。

### R3 · 不阻塞、安全
- finalize 异常只记日志不阻塞 tick；仅对 `slug='builder'` 的 tick 生效；幂等可重复跑。

## Consequences

- ✅ 工厂不再产「半成品壳」——建完必收尾（就绪+激活+按钮），用户不用等工程师手动补。
- ✅ 与 R5 自解决环互补：建期确定性收尾 + 运行期遇缺口委托 Builder 修。
- ✅ 幂等 → re-tick / 重跑安全，不刷屏。
- ⚠️ MCP 选择用「绑定→回退受管」启发式；多 MCP colony 需更精确的关联（后续）。
- ⚠️ 仍未解决 LLM 漏设 startup_command 等「注册质量」问题——finalize 用现状尽力（缺则探活/instructions）。
- 后续可进一步：把整条工厂从「超长协议一气呵成」改造为「确定性编排 + 每步校验」。
