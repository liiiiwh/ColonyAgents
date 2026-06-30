# ADR-016 · 开箱自动初始化 + 默认模型 UI 化（OSS 友好）

**Status**: Accepted (2026-06-15)
**Amends**: ADR-014（不做模型降级兼容 · 模型选择是用户职责 / fail loud）
**Builds on**: ADR-015（is_install + platform-install 两层 seed）

## Context

要把 Colony 发成 GitHub 开源项目,需要 OSS 用户「装好 → 几乎零摩擦就能用」。两处现状卡住这个目标:

1. **默认模型 env 写死**:`DEFAULT_AGENT_MODEL_ID` / `DEFAULT_SUPERVISOR_MODEL_ID` 在 `config.py` 固定成某个模型串(如 deepseek/qwen),`seed_builder_project` 拿它去 LLMModel 表反查。OSS 用户带的是**自己的 provider**(可能是 OpenAI / 任意),env 写死的串在他的模型表里找不到 → platform-install **静默跳过** → 「假装装好其实没 Builder」。
2. **初始化需手动**:ADR-015 的 InstallWizard 要用户点「一键初始化」。但更人性化的目标是:用户**只配 LLM provider**,其余全自动。

而 ADR-014 立了「模型选择是用户职责、服务不替用户选模型」的铁律——所以不能「自动猜一个模型给用户用」。

## Decision

### D1 · 默认模型解析 UI 化(不违反 ADR-014)
把「选默认模型」从 env 写死**搬到 UI**,解析顺序:
```
system_settings['default_supervisor_model_id' / 'default_agent_model_id']（用户在 UI 选）
  → env DEFAULT_*_MODEL_ID（向后兼容 / 高级用户）
  → fail loud（无任何默认 → 报错,不静默猜）
```
- 用户在 onboarding「配 provider」步骤里**显式勾一个模型为默认**——仍是**用户在选模型**,符合 ADR-014;只是把选择点从 `.env` 搬到界面。
- 不引入「自动挑第一个 enabled 模型」之类的隐式替换(那会违反 ADR-014 的精神)。

### D2 · 自动 platform-install 触发
- **后端 hook**:用户在 UI 设定默认 supervisor/agent 模型后,若 `is_install=0` 且默认模型可解析 → 自动跑 platform-install(幂等)→ 置 1。
- **启动兜底**:app 启动时若 `is_install=0` 且默认模型已可解析(重启后场景)→ 自动跑。
- `AUTO_INSTALL=true`(CI/dev)逃生舱仍在(ADR-015)。
- 「一键初始化」按钮降级为**手动补救入口**(自动没触发时可点),不再是主路径。

### D3 · OnboardingFlow（一步 + 全自动）
唯一手动动作 = **配 provider + 选默认模型**;之后自动 install + 自动引导进 **Builder 对话**(用户一句话描述 → Builder 设计出第一个 ATA 助理)。仪表盘「Getting started」进度卡 + 各页空状态 CTA 兜住关键路径。

## Consequences

- ✅ OSS 用户带任意 provider 都能开箱:UI 配 provider + 选默认模型 → 自动初始化 → 进 Builder。
- ✅ 不违反 ADR-014:模型仍由用户显式选,只是搬到 UI;无默认仍 fail loud。
- ✅ 自动 install 去掉「假装装好」陷阱(默认模型可解析才会 install)。
- ⚠️ `seed_builder_project` 解析默认模型的代码要从「只读 env」改为「先读 system_settings」——所有取默认模型的点必须走统一解析函数,否则 env 与 UI 两套值漂移。
- ⚠️ 自动触发 install 必须**幂等 + 加锁**(避免设默认模型的请求与启动兜底并发重复 seed)。
- ⚠️ 默认模型被删/禁用后要能重新引导用户去选(否则 super/worker 跑不起来),onboarding 卡需对「默认模型失效」也给提示。
