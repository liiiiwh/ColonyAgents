# ADR-014 · 不做「模型可用性降级兼容」——模型/provider 选择是用户职责

**Status**: Accepted (2026-06-07)
**Rejects**: 架构评审 cand④（「Agent 模型可用性校验 + 自动降级」）

## Context

端到端验证时反复卡在同一处：super 默认模型指向 provider 不 serve 的 `claude-opus-4-…`
（`model_not_found`）、`gemini` key 过期 → 每个 tick 在 LLM 调用处炸。架构评审据此提出
**cand④**：建/激活 agent 时探模型可达性、不可用则**自动降级**到一个可用模型 + 告警。

## Decision

**否决 cand④。不在服务里内置「模型可达性探针 + 自动降级兼容」。**

理由（用户拍板，load-bearing）：
- **模型 / provider 的选择是最终用户的职责**，不是平台该背的兼容负担。
- 「自动降级兼容」会让服务**臃肿**，且**掩盖真正的配置错误**（用户以为配了 opus，实际被悄悄降级到别的模型，行为与预期不符却无感）。
- 正确姿态是 **fail loud**：配了不可用的模型 = 配置错误，就让它显式失败，由用户去改 `.env` /
  修 provider channel / 续 key，而不是服务替它兜底。

**改为：**
- 默认模型由用户在 `.env` / config 里统一指定，存量 agent 全部 `model_id` 切到该模型：
  - 初版统一 `qwen3.6-plus`；
  - **2026-06-08 改为 `deepseek/deepseek-v4-pro`**（qwen3.6-plus 实测无法稳定驱动 11 步 Builder
    工厂协议——空转、不建项目，印证评审「工厂过度依赖长 LLM 协议」一项；换更强推理模型）。
- 要用别的模型：在 `.env` 覆盖 `DEFAULT_*_MODEL_ID`，并自行保证该 provider/模型可用。

### DeepSeek thinking 关闭（配套，非降级兼容）

DeepSeek V4（deepseek-v4-pro/flash）**thinking 默认开**，官方 thinking_mode 文档唯一关法是
`extra_body={"thinking":{"type":"disabled"}}`（OpenAI SDK 透传 body）；`reasoning_effort`
对 DeepSeek 无效。`thinking_policy` 原来把 deepseek 误并入 reasoning_effort 兜底分支 → thinking
**没真关**。已在 `compute_thinking_model_kwargs` 单列 `is_deepseek` 分支，无论 native
（provider_type='openai'）还是 compat 代理路由都下发 extra_body thinking:disabled。
注：这属于「按模型家族下发正确关参」（一直有的 per-family 矩阵），不是 ADR-014 否决的降级兼容。

## Consequences

- ✅ 服务精简——不引入模型探活 / 降级 / 周期体检这套兼容机制。
- ✅ 配置错误**显式暴露**（不被降级悄悄掩盖），排障更直接。
- ✅ 解锁 live 验证：统一可用模型后，super tick / ① 自优化闭环可真实跑。
- ⚠️ 代价：用户须自己保证 `.env` 里配的模型在其 provider 下可用；配错会在运行期显式报错
  （`model_not_found` 等），这是**有意为之**的 fail-loud，不是 bug。
- 未来若确有「多 provider 热切换」诉求，应作为**独立的 provider 管理特性**显式设计，而非藏在
  agent 运行路径里的隐式降级。
