# ADR-026 · mission 默认全自动·完全授权（唯独 Builder 例外，per-super 可配）

**Status**: Accepted (2026-06-29)
**Builds on / revises**: ADR-025 D3（审批暂停不变式 + `force_human` 必落卡）、ADR-012（propose-confirm onboarding：super/Builder 首跑提议-确认）、ADR-009（Builder governance）

## Context

mission 的 `auto_approve` 原本默认 `False`：super 每次 `request_approval` 都落卡、`paused_clarification` 等真人点。对 Colony「一句话造助手、它自己持续跑」的定位，这个默认很折磨——用户建完一个助手后，routine 审批（确认选题/确认发布前的常规步骤）每步都要盯着点，自动化体验断裂。

直觉是把默认翻成 `True`（全自动·完全授权）。但**全局无脑 True 有一个致命例外：Builder**。Builder 的 DESIGN_SUPER 流程核心就是 propose-confirm（ADR-012）——提议「Confirm the plan?」让用户审查设计方案后再动手建。若 Builder 的设计会话也默认 auto_approve，它会**自动确认自己的设计方案**直接开建，用户失去审查/调整设计的唯一机会。

所以需要：**默认全自动，但 Builder 例外，且这个默认能按 super 配置**（未来可能还有别的「需要人审」的系统 super）。

## Decision

### D1 · per-super 默认开关，全局缺省 True，Builder 种子 False
- 新增 per-super 配置位 `Agent.extra_config.mission_default_auto_approve`（bool）。
- **全局缺省 = `True`**：`create_mission` 读不到该 key 时按 True 走；`Mission` 模型默认也保持 True，二者一致。
- **唯独 Builder super 在种子数据里显式设 `false`**（`seed_builder_project`），使 Builder 设计会话默认回到 propose-confirm 人审。
- 平台级单一 system_setting **不够**——它无法让 Builder 与用户 super 区别对待；故下沉到 per-super（`extra_config`）。

### D2 · 快照语义：create-time 读一次，不回溯
- `create_mission` 在**新建那一刻**读 super 的 `mission_default_auto_approve`（缺省 True）→ 写进该 mission 自己的 `auto_approve`。
- 之后管理员改 super 这个开关，**只影响该 super 以后新建的 mission，不回溯**已存在的 mission。
- 单个已建 mission 的授权模式由它自己的 `AutoApproveToggle`（已存在）实时控制。
- 职责切分清晰：**super 开关 = 新 mission 的默认模板**；**mission toggle = 单 mission 的实时开关**。两者不打架。

### D3 · `force_human` 不变式不受影响
auto_approve 只让 **routine 审批瞬时自动通过、不落卡**（不暂停照跑）。真正需要真人在场的门——`force_human=True`（扫码绑微信 / 付款 / 「跑到 X 停下来问我」）——**无视 auto 照常落卡 + `paused_clarification` 等真人**（复用 ADR-025 D3 + `domain/auto_approve.resolve_auto_approve`）。即「默认全自动」不等于「越过人工硬门」。

### D4 · UI：Agent 配置页显式开关（仅 super）
Agent 配置编辑页加一个显式开关「新建 Mission 默认全自动·完全授权」，绑 `extra_config.mission_default_auto_approve`，**仅 `kind='super'` 显示**（worker 不建 mission）。Builder 打开该页时开关默认是关的（种子 false），管理员可手动打开。

## Considered alternatives

- **全局 `True` 无例外**：最简单，但 Builder 会自动确认自己的设计方案直接开建，用户失去审查设计的机会——破坏 ADR-012 propose-confirm 核心 UX。被否。
- **保持全局 `False`（原默认）+ 仅 worker-opt 显式 True**：与「一句话自动跑」定位冲突，用户建完助手后每步 routine 审批都要盯着点。被否。
- **平台级单一 `system_setting` 控所有 mission 默认**：无法让 Builder 与用户 super 区别对待（Builder 需人审、用户 super 要全自动）。被否，改用 per-super `extra_config`。
- **改 super 开关连带回溯改名下所有现存 mission**：会突然翻掉用户已手动调过的单 mission 设置，违反「单 mission 由自己 toggle 实时控」的直觉。被否，采纳 D2 快照语义。
