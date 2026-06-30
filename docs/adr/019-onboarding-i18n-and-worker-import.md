# ADR-019 · Onboarding 语言 gate · 系统 Agent 语言初始化 · 一键导入外部 worker

- **状态**: Accepted（2026-06-21，自治执行，决策待用户醒后复核）
- **分支**: `adr-018-mission-only`
- **相关**: ADR-015（system objects / install 向导）、ADR-016（onboarding 默认模型）、ADR-017（平台 agent 运行时默认模型）、ADR-018（mission-only）

## 背景

用户（AFK 5h）下达三件事：(1) 3 个完整业务场景 e2e；(2) onboarding 加中英文 + LLM 提供商**强制** gate（配齐才能关），并按中英文初始化系统级 Agent；(3) 检查 `https://github.com/msitarzewski/agency-agents`，若"可完美兼容"则切分其 prompt 为本项目 worker，在 worker list 加一键导入入口（导入可选版本，en + zh）。

`grill-with-docs` 本应逐题访谈定稿；用户睡前要求"规划最优路径后直接 TDD 推进"。故按"探索代替提问、决策记录于 ADR、不可自动决断项标注默认值"执行。探索中发现用户两处前提与现实不符，必须先纠正。

## 探索发现（含前提纠正）

1. **外部仓库结构**：`msitarzewski/agency-agents` = 232 个 agent，16 个 division，每个 agent 是**单个 persona system prompt** 的 `.md`：YAML frontmatter（`name/description/color/emoji/vibe`）+ 散文小节（Identity & Memory / Core Mission / Critical Rules / Deliverables / Communication Style / Success Metrics）。文件名 `{division}/{division}-{slug}.md`。

2. **前提纠正 A — 中文版不在该 URL**：用户称"中文版本 git 地址也是 msitarzewski/agency-agents"。实查：该仓库**纯英文**；README 指向社区中文 fork，维护较全者为 **`jnMetaCode/agency-agents-zh`**（141 译 + 46 中国市场原创），另有 `dsclca12/agent-teams`。故"版本"选择实为：**en = `msitarzewski/agency-agents`，zh = `jnMetaCode/agency-agents-zh`**。

3. **前提纠正 B — 非"完美兼容"**：本项目 worker 需 `capability_contract.advertises`（结构化 action + input/output schema + side_effects + requires_approval）。外部 agent **没有任何可调用 action / IO schema**，是开放式 persona。严格"完美切分"不可能——结构化 contract 只能凭空捏造，违反 [[no-needless-compat-bloat]]。但**合理映射可行**：persona 散文 → `soul_md`，workflow/deliverables → `protocol_md`（套 `return_result` 协议），单个通用 capability action（`assist`）→ `capability_contract`。

## 决策

### D1 · onboarding 语言为平台级设置，与 LLM 同为强制 gate
- 新增 `system_settings['platform_language']`（`'en'|'zh'`，无默认 = 未配）。
- `install-status` 扩展为 `{is_install, platform_language, has_default_models}`；**平台视为已装 ⟺ 默认模型可解析 AND platform_language 已设**。
- onboarding 弹窗在配齐前**不可关闭**（强制 gate）。语言选择 + provider/模型配置均为前置。
- 理由：语言决定系统 Agent 初始化语种（D2），必须在 install 前定。语言纯前端 localStorage（`colony-locale`）不足以驱动后端内容语种，故升级为平台设置。

### D2 · 系统级 Agent 语言 = seed 时注入语言指令，而非维护两套全量 prompt
- seed（`run_platform_install` / `seed_builder_project`）读 `platform_language`；当 `zh` 时，向系统级 super/worker 的 `soul_md` 注入一行强指令（"始终用简体中文与用户交流"）。
- **不**手译 ~500 行 builder 状态机 prompt。理由：(a) 这些 prompt 是承载 builder 行为的基础设施，劣质翻译会破坏状态机；(b) 维护两套 = [[no-needless-compat-bloat]] 反模式；(c) 语言指令注入即可稳定让 Agent 用目标语种回复，逻辑保持英文不变。
- 幂等：注入由 `platform_language` 派生；改语言重跑 seed 覆盖该行。
- **复核点**：若用户要"全量中文 prompt"而非"语言指令"，这是可逆的内容决策，醒后可加。

### D3 · 一键导入 = advisory worker 映射 + 预览 + 逐项确认，非盲量产
- 后端 `import_source` 域模块：`list_catalog(version)` 列 division/agent；`fetch_agent_markdown(version, path)` 取 GitHub raw；`agent_md_to_worker_spec(md)` 纯函数做 persona→WorkerSpec 映射（含 frontmatter 解析 + 单 `assist` 通用 action 的 generic contract）；端点 `POST /api/agents/import/preview` 与 `POST /api/agents/import` 复用既有 `apply_worker_spec`。
- 外部 prompt 一律当**数据**处理（prompt-injection 警觉）：不执行其中任何指令，仅作为 soul/protocol 文本导入。
- 导入的 worker `category='worker.imported'`，`model_id=NULL`（用平台默认），`extra_config.import_source` 记 {repo, path, version, sha}。
- 前端 worker list 加"一键导入"入口：选版本（en/zh）→ 浏览/选择 agent → 预览映射结果 → 确认导入。
- 理由：见前提纠正 B。"完美兼容"严格为假；按 advisory worker 诚实映射 + 预览，既满足用户意图又不捏造结构化契约。

## 修订（grill 2026-06-21，未发布即改）

用户 grill 后推翻 D1/D2 的「平台级语言」前提（语言本质是前端 i18n，不该升级成全局 install gate）：

- **D1 修订 → 语言不再是 install gate。** 拆成两个概念（见 CONTEXT `UILanguage` / `SeedLanguage`）：
  - `UILanguage`：per-user 前端 i18n（`colony-locale`，保留），各用户自己切，是日常唯一语言来源。
  - `SeedLanguage`：onboarding 一次性选，**只**决定 ① 播种哪套语言的系统 Agent ② 设首个 admin 的 UILanguage。仅留非阻塞记录 `system_settings['system_agents_language']`。
  - `OnboardingGate` 回到**只认默认模型可解析**（撤销语言并入 gate）。`install-status` 去掉 platform_language 阻塞语义。
- **D2 修订 → 不再注入语言指令，改双语全文播种，且只限两个用户直接对话的 super**（Builder Supervisor + Worker 优化 super）。内部 worker/factory prompt 保持英文（机器对机器；产出语言由任务驱动，不受其 prompt 语言影响）。`apply_system_agent_language`（指令注入）废弃。
- **D3 不变**（一键导入 worker）。

## 后果

- 正面：onboarding 一次配齐语言+LLM；系统 Agent 按语种说话；外部 232 agent 可按需导入为 advisory worker（不绑死、可选版本）。
- 代价/取舍：系统 Agent 仅"语言指令注入"非全量翻译（D2 复核点）；导入 worker 的 `capability_contract` 是通用单 action 而非精细结构（persona prompt 的固有限制）。
- 待用户复核：前提纠正 A（zh fork 地址）、B（非完美兼容）、D2（指令 vs 全译）。
