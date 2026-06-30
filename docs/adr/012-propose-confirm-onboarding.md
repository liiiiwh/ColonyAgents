# ADR-012 · 提案-确认式 onboarding + 新标签交接 + 快速自解决环（修订 ADR-011）

**Status**: Accepted (2026-06-06)
**Supersedes**: ADR-011 的「Builder 首跑中继」(R4b 透传 / R5 回灌)——改为更轻的「新标签交接」。
**Builds on**: ADR-009（治理升级）、ADR-010（能力自动就绪 / run_shell）

## Context

端到端体验暴露几个问题：
- 首跑征询用 **7 字段空表单**（赛道/风格/受众/语气/禁忌/参考号/频率）——太复杂，用户没心情填。
- 二维码 base64 在审批卡里**显示为原始文本**（ApprovalCard 只渲染纯文本）。
- 顶部 paused_reason 写「需人类残留」——别扭。
- 用户希望 agent **多想、主动提方案**，自己只 change 一下；以及 agent 多用 shell 自理、别每次等改代码。
- ADR-011 中继让 Builder 太重；用户改主意：Builder 建完只**启动 super 首 session + 给个进入按钮**，
  用户**新标签**跳进去，onboarding 在 super 自己会话里闭环。

## Decision

### R1 · 提案-确认式首跑征询（取代复杂表单）
- super soul §0 改为：首跑读用户目标（goal_spec / 建期那句话）→ **自己草拟一份具体方案**
  （赛道·风格·受众·发帖节奏·内容方向·首阶段打法）→ `request_approval(title, message=<方案>,
  options=['就这么干','我要调整','我自己说想法'])`。
- 「我要调整 / 我自己说」→ 本轮结束等用户自由文字 → super 读到后**改方案重发卡** → 直到
  「就这么干」→ memory_write 存 goal_spec.account_profile，开始运营，不再问。
- 用户人就在 super 会话里，自由文字天然到达 super（无需中继）。

### R2 · 新标签交接（取代 ADR-011 中继）
- Builder 建完调 `activate_super_first_run`（保留，去掉挂中继；只确保 super daemon session +
  kickoff 首跑）；Builder 末轮输出带 super slug → 前端在 Builder 会话渲染「进入 super →」按钮。
- 按钮 + 后台 `/admin/agents`、`/super/[slug]` 的「进入工作台」一律 **新标签打开**（target 模式 /
  `window.open(url,'_blank')`）。
- onboarding（方案卡 + 调整 + 扫码）全在 super 自己 session。**ADR-011 中继 R4b/R5 退出主流程**
  （代码留存不碍事）。

### R3 · QR 卡落在 super 会话
- Builder 建期跑 `mcp_ensure_ready` 时传 **super 的 project_id**（而非 Builder），human-qr/密钥卡
  投到 super 项目 → 用户跳进 super 页即见、即扫。

### R4 · 卡片渲染 markdown + 图片（一次性通用前端能力）
- ApprovalCard / 人类残留卡的 message 由纯文本改为**渲染 markdown（含 `![](data: / http 图片)`）**。
- 一次性：以后任何 agent 往任何卡塞图/富文本都能显示，不再逐能力改代码。

### R5 · 快速自解决环（Builder-only shell，扩自主而不扩注入面）
- run_shell **仍只 Builder**（保 ADR-010 注入安全）。
- 任何 agent 撞「能力/基建缺口」（缺工具、服务没起、要装包/转格式）→ 走 ADR-009 升级到 Builder →
  **Builder 自动跑 shell/clawhub/mcp_ensure_ready 修好 → resume**，全程无需工程师改代码。
- 各 agent 主动用现有工具自产物（如 worker 有 base64 → s3_upload 拿 URL 再返回），protocol 鼓励。

### R6 · 文案
- paused_reason / 卡片里「需人类残留」→「**需人工介入**」。

## Rollout（TDD 分阶段）

- **R6 + R4**（快、可见）：改名 + ApprovalCard 渲染 markdown/图片（QR 立刻能扫）。
- **R3**：mcp_ensure_ready 接受 target project_id，QR 卡落 super 会话。
- **R2**：activate_super_first_run 去中继 + Builder 末轮「进入 super」按钮信号 + 前端新标签（按钮/进入工作台）。
- **R1**：super soul §0 提案-确认模板（草拟方案 + 3 选项 + 调整环）。
- **R5**：快速自解决环（升级 category=capability_gap → Builder 自动 shell 修复 → resume）。
- **E2E**：清数据 → 一句话建 super → 进入按钮(新标签)进 super 页 → 方案卡(就这么干/调整) → 扫码 → 运营闭环。

## Consequences

- ✅ 用户只「确认/微调方案 + 扫码」，不填复杂表单；agent 主动提方案。
- ✅ Builder 轻量（只建+交接）；onboarding 在 super 会话闭环，自由文字天然到达。
- ✅ 卡片渲染图片是通用能力，QR/未来富内容都受益。
- ✅ shell 自主扩了「体感」（系统自解决）但注入面仍只 Builder。
- ⚠️ ADR-011 中继代码退役但保留；新标签交接需前端配合（按钮 + window.open）。
