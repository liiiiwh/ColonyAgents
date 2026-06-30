# ADR-010 · 能力自动就绪与补救 · 声明式 readiness manifest + 通用 resolver + run_shell 门 + 人类残留卡

**Status**: Accepted (2026-06-05)
**Builds on**: ADR-009（Builder 治理闭环 / escalation auto-wake / worker_health）、mcp_autostart（启动期本地 http MCP 自动拉起，commit 4addfa0）

## Context

排查「为什么有两个 xhs-mcp / Builder 能不能自己启动 MCP」暴露的根因：能力（MCP/集成）从「装好」到「真正可用」之间存在一串**就绪缺口**（二进制没装、server 没起、没登录、缺密钥），目前全靠点解决方案（clawbot 扫码、clawhub setup_instructions、mcp_autostart 拉起）零散覆盖，没有统一机制；缺口出现时要么静默失败、要么把长报错塞进 escalation 让人手工处理。

用户诉求（grill-me 共识）：**agent 运行时自动检测到就绪缺口 → 能用 shell 自动修就自动修 → 只在不可外包的人类残留处找我**；以后其它集成场景也走同一套；实在修不了就告诉我**具体操作步骤**。

| 能力 | 现状 | 缺口 |
|---|---|---|
| 本地 http MCP 启动 | mcp_autostart（启动期）/ mcp_server_restart（worker 自愈） | 仅「启动」一个环节；装二进制/登录/密钥无统一处理 |
| 需人工的外部配置 | clawhub `needs_external_setup`+`setup_instructions`+approval；clawbot 扫码（**阻塞**式） | 每集成手写专用流程，不通用；扫码阻塞 tick；无「完成后重新探针确认」 |
| agent 自动跑 shell 修复 | 仅专用 subprocess（mcp 重启 / ffmpeg） | 无通用 run_shell；无安全门；Builder 无法据集成信息自动补救 |
| 「修不了告诉我步骤」 | paused_reason 自由文本 | 不结构化、不可操作、完成后不自动复验 |

## Decision

### 安全姿态（grill-me 用户拍板，逐项记录取舍）

用户在每个安全分叉都选了**最大自动化**档，且为知情决策（已三次听取风险分析）：

- **run_shell = 通用 shell**，作用域 **仅 Builder**（worker 泡在不可信业务内容里，只负责*检测+上报*；Builder 只见 escalation 元数据，负责*执行*）。
- **无人工授权、无沙箱**：命令以 backend 同权限跑。唯一预防层 = 一个**简单快速的 LLM 安全门** + 确定性 **denylist 硬拦** + **不可变审计日志**。
- 安全门必须按对抗式构建（载重全压在它身上）：**判断命令字面效果、显式忽略随命令附带的任何「安全/已批准」说辞**（那是攻击者可控文本，正是欺骗向量）、**不确定即拒**。
- 用户接受「会装未读过的第三方包，由安全门判断、不要人工」。
- **工程师留档的未采纳建议**（零摩擦补偿控制，留作 build flag，用户可随时开）：run_shell 以**专用低权限 OS 用户**跑 + 全局 **kill-switch**。把「全面妥协」降为「有界妥协」，不加任何点击、不破坏任何安装。

### R1 · 声明式 readiness manifest（每个 MCP 一份，Builder 装时自动生成）

- `mcp_servers.readiness_manifest` JSON：
  ```
  {
    "deployment": "local" | "cloud",
    "requirements": [
      {"id": "server_up", "kind": "auto-shell",   "probe": {...}, "remediation": {...}},
      {"id": "logged_in", "kind": "human-qr",      "probe": {...}, "remediation": {...}},
      {"id": "api_key",   "kind": "human-secret",  "probe": {...}, "remediation": {...}},
      ...
    ]
  }
  ```
- `kind ∈ {auto-shell, human-qr, human-secret, human-tos, instructions}`。
- `deployment` 选模板：**local** = 装二进制→起 server（auto-shell）+ 可能登录（human-qr）；**cloud** = 通常只 human-secret（填 key），偶尔 human-tos，无 shell。
- **生成**：Builder 装/接 MCP 时，据 MCP 工具内省（如有 `check_login_status`/`get_login_qrcode` → 推 `logged_in: human-qr`）+ 包元数据，自动写 manifest。probe 与 remediation 分类静默自推；auto-shell 命令亦自动写（**无人工确认** —— 用户拍板）。

### R2 · 通用 resolver `ensure_ready(db, mcp_server_id)`

- 走 manifest，对每个 requirement：跑 **probe**（具体检查：server 探活 / 调 `check_login_status` / 查 env-key 是否在）→ 未满足则按 `kind` 派发 remediation。
- 返回 `{ready: bool, pending: [requirement...], actions_taken: [...]}`。
- 全绿 → ready。有 human-* 未满足 → 触发 R4 人类残留卡 + 暂停。
- **检测姿态**：reactive 触发由 **LLM 驱动**（worker 工具调用异常时，worker LLM 识别「像就绪问题」→ 触发 ensure_ready），不设确定性错误分类前置层（用户未采纳「确定性探针优先」）。manifest 内 probe 仍是具体检查（端口/登录态不可「LLM」，直接查）。

### R3 · `run_shell` skill + 安全门（Builder 作用域）

- `run_shell(command, cwd?, reason?) → {ok, stdout, stderr, exit_code, audit_id}`。
- 执行前管线：**denylist 硬拦**（`rm -rf`、`sudo`、`curl|sh`、写 `~/.ssh`/凭证、已知外泄模式）→ **LLM 安全门**（简单快、判字面效果、忽略说辞、不确定即拒）→ 跑 → 写 **不可变审计日志**（命令、判定、stdout/stderr、退出码、发起 agent/session）。
- 默认 **deny-on-uncertainty**。门拒 → 返回结构化拒绝（不抛崩）。
- auto-shell remediation 经此执行。

### R4 · 人类残留卡 + 非阻塞暂停/恢复（通用底座）

- 复用 `request_approval` 的 SSE+落库+审批通道（message 支持 markdown 图片 → 可嵌二维码，clawbot 已验证）。
- 新增 `request_human_action(kind, title, body, probe_ref)`：渲染卡（human-qr 嵌二维码 / human-secret 走 `request_structured_input` 表单 / human-tos 嵌条款+同意 / instructions 列具体步骤）→ **项目进 waiting 态**（复用 `paused_waiting_capability`，paused_reason 前缀 `readiness:`）→ **tick 结束释放资源**。
- 用户在平台完成（扫码/提交 key/同意/点「我已完成」）→ 平台 **resume + 重跑对应 probe 复验** → ✅ 继续 / ❌ 刷新步骤再等。
- **不阻塞**（弃 clawbot 阻塞轮询模式）。「修不了告诉我步骤」= `kind=instructions` 走同一卡+复验环。

### R5 · 触发时机：装时主动 + 运行时反应

- **proactive**：Builder 装/接 MCP 后立即 `ensure_ready` → 扫码/填 key 卡在你正配置时弹出（人类残留前置）。
- **reactive**：运行期 worker 调 MCP 失败（登录过期/server 挂）→ LLM 识别 → 重跑 `ensure_ready` 自愈。

### R6 · 范围与共用管道（用户唯一显式 ratify 项）

- readiness 引擎只管「**工具存在但未就绪**」；「**工具压根不存在**」（缺 worker/skill）仍走 ADR-009 治理升级。
- 两者**共用同一套 R4 human-card + 暂停/恢复底座**（不重复造人机交互通道）。

## Rollout（TDD 分阶段 · 依赖序）

- **R3** run_shell + denylist + LLM 门 + 审计（底座，纯逻辑 denylist/门可先红绿）
- **R1** readiness_manifest 模型 + schema + Builder 自动生成（含 local/cloud 模板）
- **R2** `ensure_ready` resolver（probe 派发 + remediation 路由，纯编排可独测）
- **R4** `request_human_action` + 非阻塞暂停/恢复 + resume 复验（复用 approval/pause）
- **R5** 装时主动（接 clawhub_install/mcp 接线后）+ 运行时反应（worker 失败 → ensure_ready）
- **E2E**：清数据（留系统基础 agent）→ 真实 LLM 跑小红书 Colony：Builder 建 super+worker→装 xhs-mcp→`ensure_ready` 自动拉起 server（auto-shell 过门+审计）→ 探到未登录→弹二维码 human-qr 卡→（人扫码）→resume 复验→worker 拿到 13 个 MCP 工具真正可用。

## Consequences

- ✅ 新集成零代码接入：写/自动生成 manifest 即可；人类只做 `{扫码, 密钥, 条款}`。
- ✅ 通用底座：readiness 与治理升级共用人机交互+暂停/恢复。
- ⚠️ **安全**：无人工授权、无沙箱、全权限 run_shell + 会装未读包 → 单一 LLM 门是唯一预防层；门被骗即全面妥协。已留低权限用户+kill-switch 作零摩擦 build flag（默认关，用户可开）。审计日志为唯一事后追溯。
- ⚠️ LLM 门有延迟与误判；deny-on-uncertainty 会偶发拦正常命令 → 转 instructions 卡让人确认。
