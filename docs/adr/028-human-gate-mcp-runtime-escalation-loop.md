# ADR-028 · 人工审批硬门（approval_judge）· MCP 平台侧运行时 · 缺能力升级闭环

**Status**: Accepted (2026-06-29)
**Builds on / revises**: ADR-026（mission auto_approve 默认 + force_human 不变式）、ADR-009（Builder 治理 / L3 escalation）、ADR-010（MCP readiness：QR/密钥卡）、ADR-012（propose-confirm / QR 留运营期）、ADR-027（capability dispatch）、ADR-018（mission-only · built_by_mission_id provenance）

## Context

真实运行（`/mission/xhs-promotion-supervisor/xhs-promotion-auto`）暴露三个咬合 bug：

1. **人工审核没停下来**：mission auto_approve=True 时，super 创作→质量审核→「人工审核」→发帖。dispatch 层对 `capability_contract.requires_approval=True` 的 action **有门**（必须先 `request_approval` 拿 ticket），但 super 调 `request_approval` **没传 `force_human=True`** → 被 auto_approve 自动通过、瞬间拿 ticket → 人工门形同虚设。审批记录里根本没有「发帖前人工审核」那条。
2. **MCP 没跑通**：发帖需 xhs MCP 支撑的 `xhs_publisher` worker。`run_shell` 跑在 backend 容器（`python:3.12-slim`，**无 git/go/node**）→ Go 项目 xiaohongshu-mcp **clone/build 不了**；且注册的 `xhs-mcp-local` **无 `startup_command`** → 无法 `Popen` 拉起 → QR 探活拿不到二维码。
3. **升级请求没被处理**：super 缺能力 → `request_new_capability` → `paused_waiting_capability` + escalation（mission_id = **发起 super 的 mission**）→ escalation_dispatcher 按 `built_by_mission_id` 正确投递到 builder mission 主 thread + 唤醒 builder tick。但 Builder 用 `mission_escalation_list`/`_count_unresolved` 按 **`mission_id == 自己的 builder mission`** 查（escalation_skills.py:70）→ 查不到 super 发来的（escalation.mission_id 是 super 的）→ Builder「没有未处理的升级请求」→ super 永远卡死。叠加：daemon tick 不加载主线程历史，Builder 看不到 `[project-escalation]` 消息。

## Decision

### D1 · 人工审批硬门：`approval_judge` 唯一裁决（request_approval 服务端自动咨询）
- 新增**系统级 worker**（capability `approval_judge`，`is_system=True`），把「哪些情况可自动、哪些必须人工」的策略**集中写进它的协议**（单一真相源、可调）。三硬停：①Agent 完全无法自动继续 ②运行阻塞 ③人类要求必须人工审核（发帖/付款/扫码/不可逆外发）。
- **`request_approval` 移除 `force_human` 参数**（grill 2026-06-30 修订）。落卡前**服务端自动调** approval_judge（`approval_judge_service.judge_must_human`，喂 title/message/options/context + auto_approve 开启状态），结构化拿 `{must_human}`：
  - `must_human=True` → 凌驾 auto_approve 强制停 + 落卡 + cancel 当前 tick（D4 接线）；
  - `False` → 按 auto_approve（开则自动过，关则 routine 人审卡）。
  - **fail-safe**：judge 不可用/解析失败 → `must_human=True`（存疑即停）。
- super 只管在 `request_approval(..., context=...)` 的 context 里讲清背景（用户要求人审/不可逆外发/「跑到 X 停」/阻塞）——**停不停由系统裁决，super 无法手动指定**。
- **为何放服务端**：实测（励志文案 super）super 会「咨询了 judge 但忘了把 must_human 传成 force_human」→ auto_approve 把人工门放行（用户 #1 投诉复现）。把「咨询+套用」变成 request_approval 内部确定性步骤，super 想漏也漏不掉。e2e 实证：auto_approve=True 的 super 跑到「请审核」→ 真停 paused_clarification + 落卡（不再 paused_idle 直接完成）。
- **不**改 ADR-026 语义（auto_approve 仍自动通过 judge 判 routine 的常规确认）。

### D2 · MCP 平台侧运行时：backend 装工具链 + QR 登录进会话
- backend 镜像装 **git + go + node** 工具链 → `run_shell` 能 `git clone` + 构建 + `Popen` 拉起 MCP server（就地运行，不引入新容器）。
- MCP 跑在**平台侧**；登录态 MCP（xhs/知乎等需账号登录）的登录走**既有 readiness `human-qr` 卡**（`ensure_ready_for_server` → `_fetch_qr_url` → 弹 pending 卡到 mission 会话），用户扫码登录。**IP/封号问题本决策明确不考虑**（用户决定）。
- Builder 注册 MCP **必须带 `startup_command`**（否则无法 auto-launch + QR 探活）——写进 Builder 协议硬规则。

### D3 · 缺能力升级闭环：按 built_by 查 + 补进 tick 上下文 + 建完 resume
- `mission_escalation_list` / `_count_unresolved`（Builder 视角）改为按**「发起 super 的 `agent.built_by_mission_id == 本 builder mission`」**查（而非 `escalation.mission_id == 本 mission`），让 Builder 可靠看到所有投递给它的升级。
- escalation 唤醒 builder tick 时，把「你有未处理升级」**enqueue 进 super_inbox**（daemon tick 不加载主线程历史，需主动喂进 tick 上下文）。
- Builder 处理升级 → 建出缺失 capability 的 worker（D2 工具链后可行）→ `resume_super_agent` 唤醒被卡的 super，闭环合上。

### D4 · Mission 生命周期门控：调度拉起→跑一轮→必落 paused（全局门控）
mission 不是常驻狂跑的 daemon，而是「调度/消息拉起 → 跑一轮（单 run_once）→ 必落某种 pause」的单元。FSM 加一态 `paused_idle`，与现有 `paused_clarification`/`paused_waiting_capability`（归为 **paused_for_human** 类）+ `stopped`/`error` 组成全局门控。

**审批门三分支**（running 跑一轮中遇审批点，先 `invoke_worker(approval_judge)` 判 must_human）：
1. `must_human=否` + mission auto_approve → `request_approval(force_human=False)` 被 `resolve_auto_approve` **自动过审 → 回 running 续跑同一轮**（自动审核主线，不暂停、不停调度）。
2. `must_human=否` + 非 auto_approve → routine 人审卡 → `paused_clarification`（可恢复，决卡即 resume）。
3. `must_human=是`（发帖/付款/扫码/缺能力）→ `force_human=True` → 永远 False → 落卡 + **硬停当前 tick → `paused_for_human`**（凌驾 auto_approve，兑现 ADR-026 D3 + 「人工审核不管 auto 都停」）。

**两类 pause × 调度器语义**：
| lifecycle | 触发 | 当前 tick | 调度 fire_one | resume |
|---|---|---|---|---|
| `paused_idle`（新增）| 阶段跑完、无门、无外部 pending | 正常收尾 | **RUN**（到点拉新一轮）| cron / 用户消息 / 手动 |
| `paused_for_human` | 审核/扫码/缺能力 | **硬 cancel 立停** | **SKIP**（观感=停调度）| 审核完成 / 扫码 re-probe / Builder resume / 用户消息 |
| `stopped` | 用户显式停 | cancel | SKIP | 用户 start |
| `error` | 异常/超时 | — | SKIP | restart / 下次 cron 重试 |

**「一阶段」定义**：一次 run_once = 一阶段；tick 自然收尾且无 force_human 门、无**外部**（用户/调度）pending → `paused_idle`。auto-drain **只消费外部 pending**，不消费 super 自塞 → 不会自我永续；撞 `max_iterations`/wall-clock 封顶也落 `paused_idle`（非 error，留待 cron 重拉）。

**调度器原则**：schedule 行 `enabled` **永不被代码自动改写**（退役 `_maybe_auto_pause_schedules` 的有损翻转）；「停/开调度器」由 `fire_one` 按 mission lifecycle 决定 run/skip 实现（保用户配置 + 崩溃安全）。

**闭合的现存洞**（全局逻辑检查）：
- **H1** 人工门落卡时**未 cancel 当前 tick** → 接线 `cancel_current_tick`（机制已存在）。
- **H2** QR/缺能力卡决了不恢复（`_resume_after_clarification` 只认 `paused_clarification`）→ 统一 `paused_for_human` 的 resume（覆盖 `paused_waiting_capability`：决卡触发 re-probe / resume）。
- **H3** 给 paused mission 发消息被 `_should_skip_tick` 吞 → 用户消息**先 paused_*→running 再触发**。
- **H4** 「阶段完成」未定义 + super 自塞 pending 永不 idle → 见上定义 + auto-drain 只消费外部 pending。
- **H5** error 无重试 → `error → 下次 cron 重试 / 用户 restart`。
- **H6** 卡死 running 无超时 → tick 加 wall-clock/max-tick 封顶 → `paused_idle`/`error`。
- **E2** 硬停是 cooperative cancel：executor 须在**每个 tool 结果后、下一次 LLM call 前**检查 `cancel_event`（人工门工具返回即在 checkpoint，保证即停而非「再蹦几个」）。

## Considered alternatives
- **人工门只靠 super 协议设 force_human**（不加 approval_judge）：本次就是这么漏的——LLM 不可靠。被否，改集中式 approval_judge worker。
- **dispatch 层对 requires_approval 硬性 force_human**（确定性兜底）：更硬，但用户选了 approval_judge worker（策略集中、可调、贴平台「一切皆 agent」）。记为可选后续兜底。
- **MCP 走独立 mcp-runner sidecar / 预打包镜像**：更隔离，但用户选「直接给 backend 装工具链」（改动最小最快通）。
- **升级改记 escalation.mission_id=builder**：丢「哪个 super 发的」归属 + 与现有语义冲突。被否，改按 built_by 查。
- **靠人工在 builder 会话推**：与「人不在也自动跑」冲突。被否。

## Consequences
- backend 镜像变大（含 go/node 工具链）+ 业务容器内跑第三方 MCP 进程（供应链/资源混职责）——用户接受，换最快打通。可后续迁 sidecar。
- 每次审批前多一次 approval_judge LLM 调用（延迟/成本）——换全局一致、可调的人工门策略。
