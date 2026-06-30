# Colony · 域词汇 (CONTEXT.md)

> 任何新代码 / 新文档 / 任何 LLM protocol_md 提到下列概念时，**必须**用本表的精确术语，禁止漂移。
> 修改一个 term 的定义 = 改本文件 + 触发跨模块同步。

---

## 核心 agent 概念

| Term | 定义 | DB 字段 / 代码位置 |
|---|---|---|
| **Agent** | 平台上的智能体单元；所有 agent 都是 `agents` 表一行 | `app/models/agent.py` |
| **SuperAgent** | `kind='super'` 的 Agent；**角色模板**（skills + capabilities + protocol_md + soul_md + model）。**平台共享**：Builder 升级 = 所有 Mission 立即生效。**不是单个项目**，同一 SuperAgent 可被 N 个 Mission 引用。 | agent.kind |
| **WorkerAgent** | `kind='worker'` 的 Agent；强落地、被动执行；平台共享标准件 | agent.kind |
| **BuilderAgent** | 平台第一个 SuperAgent (slug=`builder`)；负责自动设计其它 super/worker | agent.kind='super', slug='builder' |
| **Capability** | WorkerAgent 在平台上注册的能力 slug (如 `xhs_ops`) | agent.capability |
| **CapabilityAction** | Capability 下的一个具体动作 (如 `xhs_ops.publish_note`) | agent.extra_config.capability_contract.advertises[*].action |
| **CapabilityContract** | WorkerAgent 暴露给 SuperAgent 的契约 JSON：actions + side_effects + requires_approval + concurrency_hint + idempotent + rate_limit + parallel_safe | agent.extra_config.capability_contract |

## Onboarding / 平台语言 / 外部导入（ADR-019）

| Term | 定义 | DB 字段 / 代码位置 |
|---|---|---|
| **UILanguage** | 用户界面语言（`'en'｜'zh'`），**per-user 前端 i18n**，各用户自己切，存浏览器 `localStorage('colony-locale')`（可选再持久化到用户记录跨设备同步）。**这是语言的唯一日常来源**——平台不存全局语言。 | `frontend colony-locale` |
| **SeedLanguage** | onboarding 一次性选的语言，**只**决定两件事：① 播种哪套语言的系统 Agent（[[seed-system-agents-bilingual]]）② 设首个 admin 的 UILanguage。**不是** install gate、**不是**每请求语言源。仅留一个非阻塞记录供幂等重播。 | `system_settings['system_agents_language']`（仅记录） |
| **OnboardingGate** | 平台「已装」判定 = 默认 supervisor/agent 模型可解析（**只认 LLM**；ADR-019 一度把语言并入 gate，已撤销）。 | `init_db._is_platform_installed` / `install-status` |
| **ImportedWorker** | 从外部 prompt 库（agency-agents）一键导入的 WorkerAgent；persona prompt 映射而来，`category='worker.imported'`，含单个通用 `assist` capability action（非精细结构化契约——persona prompt 固有限制，见 ADR-019）。 | agent.category='worker.imported', extra_config.import_source |
| **ImportVersion** | 导入"版本" = 源仓库：`en`→`msitarzewski/agency-agents`，`zh`→`jnMetaCode/agency-agents-zh`（社区中文 fork，非同一仓库）。 | `app/domain/import_source` |

## Mission / Session / Activity（v6 核心重塑）

| Term | 定义 | DB 字段 / 代码位置 |
|---|---|---|
| **Mission** | SuperAgent 的**一次实例化**，也是用户面的**工作站**：自己的 memory / schedule（含是否自动执行）/ live（worker 调用实况）/ workspace / 一条消息流。同 super 可有 N 个 Mission，各自独立。**DB 表已改名 `missions`（ADR-022）**；UI / API / 文档一律说 Mission。 | `missions` 表（ADR-022 改名） |
| **~~Mission.goal_spec~~（已废弃 · cand②）** | 原意「mission 目标+完成条件+capabilities」，但**运行时从不被读**（tick/prompt 链路不读，目标 tab 已删）→ cand② 废弃。**运营目标 / account_profile / 完成条件一律写进 MissionMemory**（每 tick 真读）。`workflow_config.goal_spec` 不再写；missions API 字段恒 None 保兼容；勿在新代码引用。 | ~~mission.workflow_config.goal_spec~~ → MissionMemory |
| **account_profile** | super 首跑提案-确认后存的账号定位（赛道/风格/受众/语气/禁忌/节奏）；存在 **MissionMemory** 里，每 tick 读回驱动运营（cand②，取代死的 goal_spec） | mission_agent_memory（MissionMemory） |
| **Mission.lifecycle** | mission 业务态状态机（见下）；v6 起为唯一权威，runtime_status 作 derived view 退化 | mission.lifecycle_status |
| **~~Session~~ / ~~Branch~~（退役 · grill 2026-06-17）** | 旧 `Mission → Session → Branch → Message` 三层塌缩为 **`Mission → Message`**。Session 实测是 Mission 之上 ~1:1 的 pass-through（多 session 是未落地的 stub）；Branch 的 rewind 早被 ADR-006 废，唯一仍在用的 super↔worker 派发线程改挂到 `messages.thread_key`。两表退役（迁移期 messages 仍可读旧 session_id/branch_id）。 | ~~`sessions`~~ / ~~`session_branches`~~ |
| **Thread** | 不是表，是 `messages` 上的一个 `thread_key` 串，区分一个 Mission 内消息的归属。**只有三类键**（ADR-020，无 orchestrator/builder/legacy —— mission-only 下 builder 对话即 builder mission 的 `main`）：`main`＝用户可见对话流（super 推理 + 用户对话 + worker 调用摘要卡）**每 mission 恒 1 条**；`worker:{super_id}:{worker_id}`（**全 UUID 不截断**，弃用旧 `super-{sid8}-worker-{wid8}`）＝每对 super↔worker 的持久派发上下文（双方记得彼此历史；worker 记忆按此键过滤）；`health`＝系统自检线。并发锁按 `(super,worker)` 逻辑键。**UI 一律称「Thread/线程」，不再叫「Session/会话」。** | `messages.thread_key`（替代 `session_id`+`branch_id`） |

## ⚠️ Activity backbone — v7 已**物理删除**（见 ADR-007）

> **v6.I/J 的 `agent_activities` 已在 V7.4 删表**（migration 050）+ **ADR-008 已物理删除 `app/domain/activity/` 整包**
> （recorder no-op stub + ActivityKind/Status 枚举 + 所有 invoke_worker/tick/approval/redirect 调用点全部摘除）+
> 删 /api/activities + 删前端 ActivityTree/useActivityStream/ChatTickCard + 删 intervene-on-activity。
> 统一为「chat 消息 = 唯一观测真相源」：super 每步落 agent_log 消息（meta.raw 带事件）。
> **不要再建议补 Activity 观测表。** intervene 走 pending_approvals/decide（ApprovalCard）；telemetry 只读 worker_invocation_log。

| 旧 Term（退役） | v7 替代 |
|---|---|
| ~~Activity / agent_activities~~ | chat 消息（agent_log + meta.raw），按 tick_id/turn_id 折叠 |
| ~~ActivityRecorder~~ | StreamingExecutor + sink 适配器（落消息 → event_bus）|
| ~~ActivityTree UI / ChatTickCard(树)~~ | chat 时间线 toTimeline + 消息驱动折叠卡 |
| ~~Intervene-on-activity (POST /api/activities/{id})~~ | 对 chat 里的 approval/clarification/redirect 卡片操作（消息级）|
| ~~worker_telemetry 读 agent_activities~~ | 只读 `worker_invocation_log` |

## Lifecycle 状态机（Mission 级）

```
                    stopped
                      │ start
                      ▼
              ┌─→ running ←─────────────────────┐
              │     │                           │
              │     │ request_new_capability    │ resume
              │     ▼                           │
              │   paused_waiting_capability ────┘
              │     │
              │     │ worker.needs_clarification
              │     ▼
              │   paused_clarification ─resolve_clarification→ running
              │     │
              │     │ super.emit_redirect_suggestion + user accepts
              │     ▼
              │   stopped (mission dies; user moved to other super)
              │
              │  exception
              └─ error ─restart→ running
```

`runtime_status` (v3 字段) 在 Phase A 后退化为 `Lifecycle.is_alive` 的 derived view；**所有写入都过 `LifecycleService.transition()`**（`app/domain/lifecycle_service.py`），它跑 FSM 校验 + PG 行锁 + 同步 runtime_status + publish event_bus（ADR-008 起不再写 agent_activities，该表/包已删）。admin 排障可用 `force=True` 跳过 FSM。

**审批暂停不变式（ADR-025 · 全平台）**：存在 pending 审批卡 ⟺ mission `paused_clarification`。落卡即 `pause_for_clarification` + `cancel_event` 砍断本轮 → **至多一张 pending 卡**（暂停态不再 tick，无从产生第二张）。调度器/cron 跳过暂停态；**仅**两条恢复路径 `resolve_clarification`→running 并续跑：① 答卡选项（卡 decided）；② 用户发消息（旧卡**关闭置灰、不可再操作**，用户消息接管驱动）。auto 模式普通审批瞬时自动通过、不落卡 → 不暂停；`force_human=True` 必落卡 → 必暂停。

## 记忆（3 层 · v6 共识）

| 层 | 表 / 字段 | 写入者 | 读取者 | 生命周期 |
|---|---|---|---|---|
| **MissionMemory** | `mission_agent_memory` (mission_id = mission.id) | super tick 期间 `memory_append` + clarification 结果 | super 每次 tick 拼 prompt | mission 长期 |
| **SuperMemory** | `agent.domain_memory_md` | super 自治 `experience_record(scope='super')`（无需 admin） | 该 super 所有 mission 的 tick prompt | super 生命周期 |
| **PlatformKB** | knowledge_bases `scope='platform'` + chunks | super `experience_record(scope='platform')` → admin 批准 | 所有 super (`knowledge_search` 默认 3 层 union) | 永久 |

## ATA 闭环关键 verb（super-only skills）

| Verb | 用途 |
|---|---|
| `request_structured_input(schema)` | super 向 user 收结构化输入（goal_spec / 配置确认） |
| `request_approval(title, options)` | super 重大决策走 user 批准 (V27/V33) |
| `request_new_capability(capability, why)` | super 缺 capability → escalation 投递到 origin builder mission（按 super.built_by_mission_id）+ super 自动 paused_waiting_capability；Builder 建出 worker 后 resume_super_agent 闭环（ADR-028 D3） |
| `approval_judge`（系统 worker · ADR-028 D1 修订） | 集中式「可自动 vs 必须人工」策略 worker，**人工门唯一裁决方**。`request_approval` **无 force_human 参数**，落卡前**服务端自动调** approval_judge（`approval_judge_service.judge_must_human`）拿 `{must_human}`：True→凌驾 mission auto_approve 强制停（ADR-026 不变式）+ cancel 当前 tick；False→按 auto_approve。super 只在 `request_approval(context=...)` 讲背景，停不停由系统判（避免 super 漏传 force_human 致人工门被 auto 放行）。硬停：①无法自动继续 ②运行阻塞 ③人类要求人审/不可逆外发。fail-safe：judge 不可用→must_human=True |
| `resolve_clarification(invocation_id, answer)` | super 回应 worker 反问（Phase I 后强制） |
| `emit_redirect_suggestion(candidates, reason)` | super 判定 mission 不适合自己 → 推荐其它 super (Q7) |
| `list_supers(keyword?)` | super 查平台其它 super 候选（redirect 用） |
| `experience_record(scope, ...)` | 写经验到 mission / super / platform KB |
| `knowledge_search(query)` | 默认 3 层 union 查 |
| `invoke_worker / invoke_workers_parallel` | super 调 worker —— **唯一规范派发面**（按 `capability:slug` 或 agent_id 解析全平台 worker，ADR-027） |
| `intervene(activity_id, verb, payload)` | 用户对 Activity 节点统一介入 (Phase K) |

> **~~MissionNode / 节点版派发 / by-node workspace~~（退役 · ADR-027）**：`dispatch_to_worker(node_name)` / `parallel_dispatch` / `mission_add_node` / `mission_nodes` 表 / `workspace[node_name]` 状态（进度/质量门/decision/交付物）/ 自动插 `quality_gate` 节点 / M2 工厂 `clone_project` —— 全部历史遗留（M2 工厂管线产物），运行库 0 行使用。**标准化到 capability dispatch**：super 花名册 = `extra_config.required_capabilities`（声明在协议）；派发按能力解析全平台 worker；缺能力 `request_new_capability`→Builder；worker 产出活在 worker thread + worker_invocation_log + S3 artifacts；审核 = super 编排审核 worker + `request_approval` 人审。

## Skill 维度（Phase B/G 协同）

| Term | 定义 | DB 字段 |
|---|---|---|
| **SkillScope** | `super / worker / builder / all` —— migration 049 已加列 + backfill 32 内置 skill；`agent_service.create_agent` auto-bind 走 `Skill.scope IN (agent.kind, 'all')` | skills.scope（v6） |
| **SkillIntent** | `dispatch / memory / approval / escalation / io / knowledge / observation` | skills.intent（v6） |
| **CapabilityIndex** | 关系型 worker action 索引 `worker_capability_actions` 表；让 Builder 按 (action, side_effects, requires_approval) 复合查询 | app/domain/builder/capability_index.py |

## Builder 自动化（Phase A 核心）

| Term | 定义 | 代码位置 |
|---|---|---|
| **AgentSpec** | Pydantic dataclass 描述 SuperAgent / WorkerAgent 完整定义；Builder 生成后 factory 事务化应用 | app/domain/builder/agent_spec.py |
| **SuperSpec / WorkerSpec** | AgentSpec 的两个子类型 | 同上 |
| **MissionSpec** | spawn_mission 的入参：super_id + name + goal_hint | app/domain/builder/mission_spec.py |
| **AgentFactory** | `apply_super_spec(spec) → SuperRef` / `apply_mission_spec(spec) → MissionRef` 事务化创建 | app/domain/builder/factory.py |
| **BackwardCompat** | WorkerAgent / SuperAgent 升级 capability_contract 时的兼容校验；deepens 现有 builder_v3_skills.validate_backward_compat | app/domain/builder/backward_compat.py |

## UI 命名

| URL | 内容 |
|---|---|
| `/super/<super_slug>` | Super **角色页**：定义 + 所有 missions 列表 + 「+ 新建 Mission」 |
| `/mission/<mission_slug>` | Mission **工作台**：3 栏（session 列表 / chat 流 / ⚙️配置） |
| `/admin/agents` | admin Super/Worker catalog 管理 |
| `/admin/system-settings` | 平台配置 |

## 写入 seam (v6 收敛点)

| 概念 | 唯一 seam | 不再允许的旁路 |
|---|---|---|
| **Lifecycle 写入** | `LifecycleService(db).transition(project_id, action, reason?, force?)` | `proj.lifecycle_status = "..."` 裸赋值 / 直接 `UPDATE projects SET lifecycle_status` |
| **Message 写入** | `session_service.append_message(db, session_id, branch_id, role, content, meta=)`（自动 publish event_bus） | `Message(...)` 直接 ORM add / 自己 publish bus event |
| **观测某步** | `session_service.append_message(... role="agent_log", meta={turn_id, raw})`（ADR-007/008：chat 消息=唯一观测源；Activity 整包已删） | ~~ActivityRecorder~~（已物理删除，勿重建）|
| **Session 活跃 branch** | `session_service.get_current_branch(db, session_id)`（带 fallback）| `is_current=True` where 子句（ADR-006 字段 deprecated）|
| **invoke_worker 前置校验** | `app/domain/dispatch/precheck.py:precheck_invocation`（V17/V37/super_id 纯函数）| 在 `_invoke_worker_inner` 里手写 if-else |
| **worker return_result 解析** | `app/domain/dispatch/envelope.py:extract_return_result_envelope`（纯函数）| 自己 reverse + try json.loads |
| **Long memory 3-tier 读** | `app/domain/memory/reader.py:assemble_long_memory_md`（mission + super + platform 提示）| 各处自己查 ProjectAgentMemory / Agent.domain_memory_md |
| **记忆写入收敛（去重折叠）** | `app/domain/memory/consolidate.py:collapse_into / fingerprint`（纯，近重复**任意位置**折成「×N」并移末尾，零 LLM；`memory_append` 已走它）| 只比**最后一段**的 last-block dedup / 裸 `existing+"\n\n"+seg` 追加（→「skip this round」一天十几万字符撑爆） |
| **LLM 异常分类** | `app/services/llm_error_classifier.py:classify_llm_error`（getattr-safe）| 自己写 `isinstance(exc, litellm.X)`（版本差异隐患）|
| **前端 SSE event dispatch** | `frontend/lib/sse/handlers.ts:dispatchSSEEvent` typed Record | `if (data.type === 'X') ...` 长链 |
| **super↔worker 对话上下文** | `app/domain/dispatch/invocation_context.py:InvocationContext`（lock + branch + history 一体；`async with ic.acquire()`）| _THREAD_LOCKS global dict / 散落 _get_or_create_thread + __load_thread_messages |
| **压缩决策** | `app/domain/compression/policy.py:should_compress / pick_compressible`（纯）| 在 maybe_compress_context 里 `if tokens < threshold` 内联 |
| **压缩摘要** | `app/domain/compression/summarizer.py:fallback_summarize / build_summarize_payload`（纯）| 在 session_service 内联 |
| **压缩执行入口** | `app/domain/compression/compressor.py:ContextCompressor(db).maybe_compress(...)` | 直接调 session_service.maybe_compress_context |
| **LiteLLM 路由 + 流式开关** | `app/domain/llm/provider_router.py:resolve_route / should_stream`（纯 switch）| 在 _build_llm 里手写 if/elif provider_type |
| **运行配置读取** | `app/core/platform_config.py:PlatformConfig.load(db)`（typed dataclass）| 散落 `system_settings.get_int(db, "magic.key", default)` |
| **批准后分叉** | `app/domain/approval/resolution.py:route_post_decision(scope, option)`（纯）| 在 decide() 里 scope if-else + 2 处 create_task |
| **微信审批意图解析** | `app/domain/wechat/intent_parser.py:parse_json_loose / fallback_classify`（纯，风控敏感）| 埋在 wechat_intent async flow 里 |
| **默认 chat LLM 解析** | `app/services/llm_resolver.py:resolve_default_chat_llm / resolve_model_for_default_spec` | `api/preview_chat._resolve_default_chat_llm`（service local-import api，分层倒置）|
| **关思考参数** | `app/domain/llm/thinking_policy.py:compute_thinking_model_kwargs`（纯，per-family 矩阵）| 在 _build_llm 里 90 行内联 if/elif |
| **tick 生命周期（in-memory）** | `app/services/tick_lifecycle.py`（registry + cancel）| 与队列混在 super_inbox |
| **pending 消息队列（DB）** | `app/services/pending_queue.py`（enqueue/pop/count）| 与 tick registry 混在 super_inbox |
| **super_chat 消息内容拼装** | `app/domain/super_chat/intake.py:build_user_message_content`（纯）| 在 POST /chat handler 内联 |
| **chat 当审批意见** | `app/domain/approval/resolution.py:build_auto_decide_option` | 领域规则裸在 super_chat handler |
| **前端 chat timeline 重建** | `frontend/lib/chat/timeline.ts:toTimeline / parseApprovalReply`（vitest 覆盖）| ChatArea.tsx 内联 413 LOC |
| **LangGraph→AISDK 事件翻译** | `app/domain/stream/event_translator.py:emit_llm_event`（纯，8 测试）| stream_service 内联 148 LOC |
| **daemon tick prompt 拼装** | `app/domain/daemon_prompts.py:assemble_super_prompt`（纯，5 测试）| project_daemon 内联 |
| **默认模型解析** | `app/domain/onboarding/default_model.py:resolve_default_model`（system_settings>env>None，3 测试；ADR-016）| seed_builder_project 内联只读 env |
| **后台 fire-and-forget 任务** | `app/core/bg_tasks.py:spawn`（强引用持有防 GC，1 测试）| 裸 `asyncio.create_task(...)` 丢返回值 |
| **mission 时间线装配** | `frontend/lib/chat/missionTimeline.ts:assembleMissionTimeline`（纯，5 测试）| mission page 内联 165 行 IIFE |
| **命令行切分** | `frontend/lib/shell/splitArgs.ts`（尊重引号，6 测试）| 裸 `split(/\s+/)` 拆坏引号参数 |
| **主题化 confirm/toast** | `frontend/components/providers/ConfirmProvider.tsx:useConfirm/useToast` | 原生 `confirm()`/`alert()`（不主题化）|
| **i18n 文案** | `frontend/lib/i18n/`（react-i18next，默认 EN，en/zh tsc 强制对齐）| 组件内硬编码中文字符串 |

## Builder 治理闭环（ADR-009）

| Term | 定义 | 代码位置 |
|---|---|---|
| **CapabilityConsumer** | 在用某 capability 的 super（声明 extra_config.required_capabilities ∪ 观测 worker_invocation_log）；改 worker 前查它 | app/domain/builder/capability_consumers.py |
| **跨 super 兼容硬阻断** | 升级共享 worker 时 analyze_worker_change_impact：任一在用它的 super 会被破坏就 raise（不能「一边好一边坏」）；用了的 action 删除即破坏，deprecated 也不行 | factory.apply_worker_spec + spec_validation.analyze_worker_change_impact |
| **BuilderWorkClaim** | Builder session 对某 mutation 目标（worker/super/skill）的独占锁；防多 session 并发改坏同一目标。build_*/install 自动抢锁，release_work_claim 释放，TTL 1800s | builder_work_claims 表 + work_claim.py + builder_claim_service.py |
| **report_worker_issue** | super 上报「现有 worker 坏了」(category=worker_health) + 停工 paused_waiting_capability(reason worker_issue:)；worker 修好后**按 capability 自动唤醒所有等待者**（ADR-025，不再依赖 Builder 手动 resume） | super_dispatch_skills.report_worker_issue_tool |
| **Work-Order Mission** | Colony Worker Optimization super 名下的 ephemeral mission，盯**单个 worker(capability)** 的一次优化：全自动跑到完成→软关闭(STOP+archived)。同一 worker 至多一个在跑（串行去重），跨 worker 并行。ADR-025 | worker_optimization_service |
| **Worker-Opt Dispatcher** | 6h 体检退化为「派发器」：只扫 worker_invocation_log 退化候选 → 给每个退化 worker spawn/attach 一个 Work-Order Mission，自己不修。6h 节律 = dispatcher mission 的**可见 MissionSchedule**（payload trigger=worker_health_scan → run_once 路由到确定性 run_health_tick，不烧 LLM；平台 cron sys-worker-health 退役）。ADR-025 | worker_health_service.run_health_tick + worker_optimization_service._ensure_dispatcher_schedule |
| **optimization_continue / optimization_done** | work-order super 自驱续跑/收尾：continue 入队下一 tick（守卫：有未决 force_human 卡则拒绝）；done 软关闭+唤醒 capability 等待者+注销调度。漏调由短间隔兜底调度补踢、max-tick 封顶强制收尾。ADR-025 | worker_optimization_service |
| **escalation auto-wake** | escalation 落 Builder session 后立即 idle-trigger 唤醒 Builder（复用 v7） | escalation_dispatcher.deliver_escalation |
| **BuilderWorkLog** | Builder 每 session 结构化变更审计（建/升了什么、影响哪些 super、结果）；GET /api/super/{slug}/work-log + 前端面板 | builder_work_logs 表 + BuilderWorkLogPanel.tsx |
| **create_skill_from_template** | Builder 受限模板化建 skill（http_api_call/mcp_proxy/prompt_macro 白名单，不跑任意代码）；解 P5 缺 skill 死锁 | skill_template.py + builder_factory_skills |
| **MissingSkillsError** | P5 缺 skill 优雅降级：build_* 返回结构化 {missing_skills, hint} | spec_validation.MissingSkillsError |

## 平台系统对象 + 自检自迭代闭环（ADR-015 · 本期）

| Term | 定义 | DB 字段 / 代码位置 |
|---|---|---|
| **SystemObject（系统对象）** | 平台自举不可删除的一组实体：Builder Project(slug='builder') + Builder Supervisor + 三 builtin worker(BuilderAgent/InstallerAgent/TesterAgent) + WorkerHealthSession。`is_system=True` 标记；前端隐删除钮，后端 delete 入口命中即 409 | `agents.is_system` / `projects.is_system`（新列）+ `sessions.scope='system'` |
| **Colony Worker Optimization（worker 优化 super · grill 2026-06-17）** | **新的系统 super,专管 worker 优化/迭代**，把职责从 Builder 分出来。单例：不可删、不可复制、不可新增 mission、自动运行，固定 1 个 mission。两条输入：①默认**定期自检**（读 worker_invocation_log 筛退化候选，接替旧 WorkerHealthSession 的 6h tick）；②**接收所有 super 发来的 worker 优化建议**。收到即走**跨调用方兼容门**（L2）优化该 worker —— 因 worker 跨 super 共享，集中在此一处、不归任何 builder mission。 | 系统 super（agents.is_system）+ 其固定 mission；接替 `sys-worker-health` |
| **~~WorkerHealthSession~~（升格 · grill 2026-06-17）** | 旧的挂 Builder 下 `scope='system'` 单例自检会话 → **升格为 Colony Worker Optimization super + 其固定 mission**（随 session/branch 退役）。Builder 不再管 worker 迭代，只管 **super 创建 + super 迭代**（super 自迭代回它的 origin builder mission，1:1）。 | → Colony Worker Optimization |
| **跨调用方行为门（cross-caller behavioral gate）** | L2 自动迭代 `protocol_md` 前后,把质检从**单项目**升级为**全调用方**：从 worker_invocation_log 取该 worker 的全部 `(super_agent_id, action)` 分布,任一调用方明显退化→自动 revert。补 `self_tune` 漏调 `analyze_worker_change_impact` 的缝 | `_quality_gate_pass_rate` 扩 cross-caller + self_tune apply 接 capability_consumers |
| **TieredFixAuthority（分级修复授权）** | 自动迭代权限分层:**可逆**(protocol_md 措辞/retry/timeout/澄清策略)→ auto-apply 过行为门+自动 revert;**不可逆**(删/改 action 语义、加 tool、动 shell-safety/高危域)→ L3 升级人工。对齐 auto_approve + force_human | self_tune + escalation_dispatcher |
| **GoldenReplay（黄金回放）** | 每 (调用方, action) 从历史成功调用挑少量真实 (params→好输出) 当 golden;迭代后回放,任一破→阻断 apply。**轻量**:集小而稳,只拦硬破坏,不限制内部行为优化(防能力退化) | worker_invocation_log 采样 |
| **is_install / InstallWizard** | 平台安装标记,存 system_settings(KV);默认 0。后台首启 `is_install=0` → 引导条「一键注入初始化数据」→ `POST /api/admin/install`(幂等跑 platform-install seed)→ 置 1 不再提示。迁移时已有 Builder Project → 直接置 1 | system_settings['is_install'] |
| **boot-critical vs platform-install seed** | `run_startup_seeds` 拆两层:**boot-critical**(admin user + builtin skills,永远自动,login 前置);**platform-install**(Builder Project + WorkerHealthSession + worker catalog + KB,仅向导触发 or `AUTO_INSTALL=true` 逃生舱) | init_db.py 拆分 |

> ⚠️ **两条 worker 变更 seam 的兼容不对称**(本期收敛点):**契约层**(`capability_contract` 经 `agent_update` → `analyze_worker_change_impact` 跨 super 硬阻断,接口删/改即 raise)已强;**行为层**(`protocol_md` 经 L2 `self_tune`)历史上**只有单项目质检、漏跨调用方门**。ADR-015 把自动迭代的行为层也收敛到跨调用方门 + golden replay,使「迭代后完美兼容所有调用方」成立。

## 生产就绪（ADR-008 · 规划中）

| Term | 定义 | 代码位置 |
|---|---|---|
| **WeChat Router** | 微信入站自由消息 → 具体 super session 的路由服务（轻量 + LLM 歧义消解，**非 super**）。1 微信账号服务 N super（ProjectApprovalChannel 多对一）；查候选→唯一直接/多个 LLM 匹配→不确定发菜单→缓存会话目标→注入 user_chat + idle-trigger | app/services/wechat_router.py + app/domain/wechat/router_policy.py |
| **MessageTickCard** | 消息驱动的 tick 折叠卡（同 turn_id 的 agent_log + assistant 聚合）；替代 V7.4 删掉的 agent_activities 驱动 ChatTickCard，复用 toTimeline 重建 tool 卡 | frontend/components/mission/MessageTickCard.tsx + lib/chat/ticks.ts |
| **审批闭环** | request_approval → pending_approvals + WeChat（带平台深链 URL）→ 人微信回 or 平台 ApprovalCard 审核 → decide() **统一触发 tick**（v7 idle-trigger，不再只 affirmative）| pending_approval_service + wechat_router |
| **Builder 工厂硬门** | apply_super/worker_spec fail-fast：capability_contract 结构校 + skill 存在性报错不静默 + 升级自动 backward_compat | app/domain/builder/factory.py |

## v7 统一流式（ADR-007 · 规划中）

| Term | 定义 | 代码位置 |
|---|---|---|
| **StreamingExecutor** | Layer 1 共享执行核心：astream_events → event_translator → yield (event, persist_action)。chat 端 + daemon 端复用 | app/services/streaming_executor.py + daemon_sink.py |
| **HTTP sink / daemon sink** | Layer 2 适配器：chat 端 yield SSE 给客户端；daemon 端每事件 append_message → event_bus | stream_service / project_daemon |
| **tick 边界插入** | 用户消息不 cancel 当前 tick；tick 一结束 auto-drain pending_queue → 立即下一 tick | streaming_executor + tick_lifecycle |
| **行为步道标签** | §3 用户消息 `[👤 用户实时插话·优先响应]` vs cron `[⏰ 定时自主运行]`；protocol 教 super 优先回应 | daemon_prompts + protocol_md |
| **观测真相源** | **chat 消息（agent_log + meta.raw）唯一**；super 每步落消息按 tick_id 折叠 | session messages |
| **当前时间注入** | `app/domain/prompt_time.py:current_time_section`（Y-m-d H:i:s + Asia/Shanghai + 周几）注入所有 agent system prompt | agent_service._collect_static_prompt_parts |
| **StreamPiece 驱动核** | `app/services/streaming_executor.py:drive_agent_events`（astream_events → (sse, persist) 序列）| chat + daemon 复用 |
| **daemon sink** | `app/services/daemon_sink.py:persist_stream_piece`（StreamPiece → append_message → event_bus）| project_daemon.run_once |
| **tick 边界决策** | `app/domain/tick_policy.py:should_trigger_now / should_drain_after_tick`（纯）| super_conversation |

> ⚠️ **dispatch_to_worker/parallel_dispatch 不能删**：Builder Supervisor protocol_md（init_db.py:342-345）用它们做
> node 编排（planner/assembler/installer 流水线）。Mission super 用 invoke_worker，Builder super 用 dispatch_to_worker，两套并存。

## V7.5 · 集成测试解锁（conftest 修复）

| 修复 | 说明 |
|---|---|
| **agent.py JSONB 跨方言** | `metrics_baseline` 原 raw `postgresql.JSONB` → sqlite create_all 抛 visit_JSONB → 阻塞 93 个集成测试。改 `JSON().with_variant(JSONB,'postgresql')`，解锁后 203→296 passed |
| **resolve_skill_scope** | `app/skills_builtin/skill_scope.py`：内置 skill scope/intent 单一映射，**seed 时就设对**（修 fresh-install 上 super-only 工具误绑 worker 的真 bug；migration 049 只 backfill 老库）|
| registry category | promote_to_platform / platform_knowledge_search 的 `category='general'`（不在 Literal）→ `utility` |

## 视觉 / i18n / 开箱（ADR-016 · 本期）

| Term | 定义 | 代码位置 |
|---|---|---|
| **DesignTokens（设计 token）** | 全站视觉的单一来源:色板(近黑深色优先 + 浅色)/排版/间距/圆角/阴影/强调色。强调色 = 紫罗兰 `#6C5CE7`。深色为默认,提供浅色模式 | `frontend/app/globals.css` + `tailwind.config` |
| **视觉方向 = 精致极简(Linear/Raycast)** | 平面深色表面 + 细边框 + 单一强调色 + 紧致排版 + 大留白 + 克制微动效。禁:重渐变/发光/拟物。改共享 `ui/` 组件 = 全站 26 页同步抬升 | ui/* 组件 |
| **品牌标记(Logo)** | 六边形 C 标记 + 紫罗兰,全站统一(favicon/登录/侧边栏/加载页) | `frontend/components/brand/Logo.tsx` |
| **i18n** | `react-i18next`,**默认英文(EN=源语言)**,中英可切,**不改 URL**,`localStorage` 持久化,顶栏 EN/中 切换。全站文案 key 化(EN+ZH 双 catalog) | `frontend/lib/i18n/` + `locales/{en,zh}/*` |
| **OnboardingFlow（开箱)** | OSS 用户唯一手动动作 = **配 provider + UI 选默认模型**;选定 → **自动触发 platform-install** → 自动引导进 Builder 对话。配合各页空状态 CTA。仪表盘「Getting started」进度卡跑完即隐 | providers 页 + GettingStartedCard + InstallBanner |
| **DefaultModelResolution（默认模型解析)** | 顺序:**system_settings(UI 选)→ env(`DEFAULT_*_MODEL_ID`)→ fail loud**。把「选默认模型」从 env 写死搬到 UI,使任意 provider 的 OSS 用户都能开箱;遵守 ADR-014(模型是用户选择,不静默替换) | system_settings + seed_builder_project |
| **自动 platform-install 触发** | is_install=0 且已配可用默认 chat 模型 → 自动跑 platform-install(provider/model 配好后端 hook + 启动兜底),免手点「一键初始化」 | install hook |
| **docker-compose 为推荐安装** | 主路径;基础设施**钉死版本**(postgres=pgvector pg16、minio 钉版本…);`up` → 自动迁移 + boot-critical seed → UI 配 LLM → 自动初始化 → 可用 | docker-compose.yml |

## 命名禁忌（防漂移）

- ❌ `invoke_super` —— v6 stub；v7 才考虑跨 super 调度
- ❌ "Project" 当 mission 概念用 —— v6 起 UI/文档/Builder protocol 一律说 **Mission**（DB 表名 `projects` 不动是历史遗留）
- ❌ "Thread" 当对话上下文用 —— 用 **Session**（用户级）或 **InvocationContext**（super↔worker 持久对话）
- ❌ "branch" 当用户对话用 —— 用 **Session**
- ❌ "agent thread" / "agent task" 含糊 —— 用 **Activity**
- ❌ "tool call" 当 worker 调用 —— 用 **CapabilityAction** 或 **invoke_worker**
- ❌ "user 会话" 含糊 —— 用 **Session**

## 写新代码 / 文档 checkbox

- [ ] 类名 / 函数名 / 文件名 用本表 term，不发明新词
- [ ] CRUD 一个 domain 实体 → 入口在 `app/domain/<entity>/`
- [ ] 写 protocol_md 给 LLM 看时也用同样 term
- [ ] 加新 term → 先改本文件再写代码

## 版本演进

| 版本 | 关键引入 |
|---|---|
| v3 | Super/Worker 二分 + capability_contract + super-worker thread |
| v4 | 统一 Agents UI + 实时 chat |
| v5 | event_bus + memory revisions + ApprovalCard + ArtifactPreview |
| **v6.F**（本期） | **CONTEXT.md + app/domain/ 骨架** |
| v6.I | Activity 模型 backbone（agent_activities 表 + recorder） |
| v6.A | AgentSpec + Factory + Project→Mission 语义重命名 + Lifecycle 统一 |
| v6.B | Capability 索引 worker_capability_actions 表 |
| v6.J | Chat 流 tick 折叠卡 + ActivityTree + Mission Bootstrap UI |
| v6.K | Intervene verb 统一 + 替代散落 4 个介入 API |
| v6.C+D | 3 层 KB scope + Builder Telemetry skill |
| v6.L | ADR-006 session model + project_daemon 用 main_runtime 直接读写（不再 per-tick branch）|
| v6.M | LifecycleService + MessageInbox + Activity APPROVAL hook + SkillScope/Intent 收尾 |
| v6.M.2 | R2 review TDD：删 legacy 黑名单 + 抽 precheck/envelope/MemoryReader/llm_error_classifier/SSE handlers + dispatch_to_worker deprecate |
| v6.M.3 | R3 review TDD：InvocationContext + ContextCompressor(policy/summarizer/compressor) + PlatformConfig(typed) + provider_router + ApprovalResolution + wechat intent_parser；修 MAX_NESTING_DEPTH NameError typo bug |
| v6.M.4 | R4 review TDD：LlmResolver(修分层倒置) + thinking_policy(修 native-openai reasoning_effort bug) + super_inbox 拆 tick_lifecycle/pending_queue + super_chat intake + 前端引 vitest + chat/timeline 抽取 |
| v6.M.5 | R5 review TDD：event_translator + daemon_prompts；运行逻辑图 + 可观测性审计 |
| **v7**（本期） | **统一流式（ADR-007）：当前时间注入 + StreamingExecutor + daemon 流式进 chat + tick 边界 auto-drain + 行为标签；conftest JSONB 修复解锁 93 集成测试；V7.4 物理删 agent_activities/ActivityTree** |

## 知识 / 记忆 / 存储（grill 2026-06-22 · ADR-023）

| Term | 定义 | 实现 |
|---|---|---|
| **知识库（KB）** | 语义检索型参考资料，**per-super 共享**（同 super 的所有 mission 共用一份；改自原 per-mission 1:1）。Builder 提案前强制 `knowledge_search` 查经验；mission 收尾 `archive_to_knowledge` 沉淀。后台 `/admin/knowledge` 可看列表 + 逐条删（已实现）。冷启动一直空的真因：① 无 enabled embedding 模型时 `_ensure_*_kb` 直接跳过建库；② archive 闭环未转。 | `knowledge_bases`（FK 由 mission 改挂 super agent） |
| **平台经验 KB** | 跨 super 的平台级经验沉淀（与 per-super KB 是不同层） | `promote_to_platform` / `platform_knowledge_search` |
| **压缩记忆（MissionMemory）** | **per-mission** 的上下文压缩产物：超阈值自动压成「压缩段」追加 + 每 tick 固定加载注入 system prompt。`/mission/<slug>` 右侧 Memory tab 已可查看 / 编辑 / 整体清空 / 版本回滚。与知识库正交（固定加载 vs 按需检索）。 | `mission_agent_memory` / `thread_agent_memories` |
| **对象存储** | Agent 交付物 / 产物的二进制存储后端（S3 / MinIO）：`write_artifact` 上传每个 deliverable，`s3_*` skill。**load-bearing，非可选**；后台 500 是 S3 凭据与 bundled MinIO 不匹配（endpoint 被覆盖到 minio:9000 但 key/secret 漏到 .env 远程值）。 | `storage_service` / MinIO |
| **~~物料库~~（退役 · grill 2026-06-22）** | 原「按 key 取结构化素材」库；与知识库职能重叠 + 协议零驱动 + 零使用 → 砍（表 / skill / API / UI 全删）。 | ~~`materials` 表 / `material_lookup` / `list_material_keys`~~ |

---

_最后更新：2026-06-22 · grill（知识库 per-super / 压缩记忆 per-mission / 物料库退役 / 对象存储凭据修复）→ ADR-023_
_早期：2026-06-15 · ADR-015 grilling（系统对象不可删除 + 自检自迭代 + 安装向导 + 跨调用方兼容门）_
