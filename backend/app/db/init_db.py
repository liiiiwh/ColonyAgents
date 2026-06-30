"""启动时数据初始化：首任管理员账号 + 内置 Skill 播种。

Provider / Agent / Mission 等业务数据一律通过后台 UI 管理，**不**在 .env 中配置。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.skill import Skill
from app.models.user import User

logger = logging.getLogger(__name__)


async def seed_admin_user(db: AsyncSession) -> None:
    """若不存在管理员账号，则按 INIT_ADMIN_* 配置创建。"""
    result = await db.execute(select(User).where(User.username == settings.INIT_ADMIN_USERNAME))
    existing = result.scalar_one_or_none()
    if existing:
        return

    admin = User(
        username=settings.INIT_ADMIN_USERNAME,
        email=settings.INIT_ADMIN_EMAIL,
        hashed_password=hash_password(settings.INIT_ADMIN_PASSWORD),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    await db.commit()
    logger.info("✅ 已创建初始管理员账号: %s", settings.INIT_ADMIN_USERNAME)


async def seed_builtin_skills(db: AsyncSession) -> None:
    """播种内置 Skill 元数据（tool_builtin 类型，is_builtin=True）。

    已存在（按 slug）的条目做轻量 upsert：更新 name / description / builtin_ref。
    元数据中已删除的旧 slug（"孤儿"）会自动 `is_enabled=False`，避免：
    - 老 agent 绑定指向无注册工厂的 builtin_ref，运行时静默掉工具
    - 前端 Skills 列表展示已废弃工具误导管理员
    （是否物理删除孤儿 Skill 由管理员从 UI 操作；自动只下架，保 data 安全。）
    """
    from app.skills_builtin.registry import BUILTIN_SKILL_METADATA
    from app.skills_builtin.skill_scope import resolve_skill_scope

    result = await db.execute(select(Skill).where(Skill.is_builtin.is_(True)))
    existing = {s.slug: s for s in result.scalars().all()}
    metadata_slugs = {meta["slug"] for meta in BUILTIN_SKILL_METADATA}

    created = 0
    updated = 0
    for meta in BUILTIN_SKILL_METADATA:
        _cat = meta.get("category", "custom")
        _scope, _intent = resolve_skill_scope(meta["slug"], _cat)  # V7.5 · scope/intent 在 seed 就设对
        if meta["slug"] in existing:
            s = existing[meta["slug"]]
            s.name = meta["name"]
            s.description = meta["description"]
            s.builtin_ref = meta["builtin_ref"]
            # M0：从 metadata 同步 category
            if meta.get("category"):
                s.category = meta["category"]
            s.scope = _scope
            s.intent = _intent
            # 重新被纳入 metadata 的（如曾被自动下架后又恢复）→ 默认重新启用
            if not s.is_enabled:
                s.is_enabled = True
            updated += 1
        else:
            db.add(
                Skill(
                    name=meta["name"],
                    slug=meta["slug"],
                    description=meta["description"],
                    skill_type="tool_builtin",
                    builtin_ref=meta["builtin_ref"],
                    category=_cat,
                    scope=_scope,
                    intent=_intent,
                    content_md="",
                    config_schema={},
                    is_enabled=True,
                    is_builtin=True,
                )
            )
            created += 1

    # 自动下架已不在 metadata 中的孤儿
    deactivated = 0
    for slug, s in existing.items():
        if slug not in metadata_slugs and s.is_enabled:
            s.is_enabled = False
            deactivated += 1
            logger.warning(
                "⚠️ 内置 Skill %s (builtin_ref=%s) 已不在 metadata，自动下架；"
                "如老 agent 仍绑定它，运行时该工具会静默缺失",
                slug, s.builtin_ref,
            )

    if created or updated or deactivated:
        await db.commit()
        logger.info(
            "✅ 内置 Skill 播种：新增 %d / 更新 %d / 自动下架 %d",
            created, updated, deactivated,
        )


async def seed_builder_project(db: AsyncSession) -> None:
    """创建 Colony 自带的 Builder Supervisor（self-bootstrap）。

    包含：
    - Supervisor Agent: `Builder Supervisor` (category='builder', slug='builder')
    - 自动绑 Builder 建造期 Skills（含 agent_aux_model_bind）到 Supervisor

    **不再** seed 任何 standing 的 Builder Mission：Builder super 没有默认 mission，
    设计会话由用户在 /super/builder 点「+新建」按需创建。存量库里残留的 slug='builder'
    standing mission 会在本函数里 cascade 删除。

    幂等：Builder Supervisor 按 name upsert，不重建。
    """
    from app.core.config import settings
    from app.models.agent import Agent, AgentSkill
    from app.models.mission import Mission
    from app.models.provider import LLMModel, LLMProvider
    from app.models.skill import Skill
    from app.models.user import User
    from sqlalchemy import or_

    # 1. 必要前置：admin user 必须已存在
    admin_row = await db.execute(
        select(User).where(User.username == settings.INIT_ADMIN_USERNAME)
    )
    admin = admin_row.scalar_one_or_none()
    if admin is None:
        logger.warning("[seed_builder_project] admin user 不存在，跳过 seed")
        return

    # 存量库清理：Builder super 不再有 standing mission（设计会话按需创建）。
    # 若历史库里仍有 slug='builder' 的 standing mission → cascade 删除（FK ondelete=CASCADE
    # 自动清 nodes / schedules / approval channel 等）。delete_mission 内部自带 commit。
    legacy_builder_mission = (
        await db.execute(select(Mission).where(Mission.slug == "builder"))
    ).scalar_one_or_none()
    if legacy_builder_mission is not None:
        from app.services import mission_service
        await mission_service.delete_mission(db, legacy_builder_mission)
        logger.info(
            "[seed_builder_project] 删除存量 standing Builder mission (id=%s)",
            legacy_builder_mission.id,
        )

    # 内置 Skill 必须先就位（否则下面 _bind Builder Supervisor 的工具会全部静默缺失）。
    # 幂等 upsert：生产启动序列里已先跑过 seed_builtin_skills，这里再跑一次也无副作用。
    await seed_builtin_skills(db)

    # ADR-019(修订) · Builder Supervisor soul 按 SeedLanguage 取双语版本（protocol 单份英文）
    from app.db.system_agent_prompts import (
        APPROVAL_JUDGE_NAME,
        APPROVAL_JUDGE_PROTOCOL,
        APPROVAL_JUDGE_SOUL,
        APPROVAL_JUDGE_SOUL_ZH,
    )
    from app.db.system_agent_prompts import soul_for as _soul_for
    from app.domain.onboarding.seed_language import get_seed_language as _get_seed_lang
    _seed_lang = await _get_seed_lang(db)
    _builder_soul = _soul_for("Builder Supervisor", _seed_lang)
    # ADR-028 D1 · approval_judge 是机器对机器 worker（不与用户对话）→ 只需单一 soul；
    # 仍按 seed 语言择中/英，便于 reason 文案贴平台语言。
    _approval_judge_soul = (
        APPROVAL_JUDGE_SOUL_ZH if _seed_lang == "zh" else APPROVAL_JUDGE_SOUL
    )

    # 2. 平台 Agent 一律以 model_id=NULL 播种 —— 运行时按 kind 解析平台默认模型
    #（ADR-017：反转 ADR-016 的「无默认模型不播种」。agents 默认就在,无 LLM 时不运行）。
    # super → 默认 supervisor 模型;worker → 默认 agent 模型,都在 build_agent_executor 运行时解析。
    sup_model = None
    wk_model = None

    # 3. 4 个 Agent（按 name upsert）
    # v4 · 新增 kind / capability 让 Builder = super + 4 子 agent = worker（统一 agent 模型）
    def _agent_spec(
        name: str,
        category: str,
        soul: str,
        protocol: str,
        model: LLMModel | None,
        *,
        produces_deliverable: bool = False,
        kind: str | None = None,
        capability: str | None = None,
        extra_config: dict | None = None,
    ) -> dict:
        spec = {
            "name": name,
            "description": f"Colony Builder built-in {name}",
            "category": category,
            # None → use the platform default model (resolved at runtime by kind).
            "model_id": model.id if model is not None else None,
            "soul_md": soul,
            "protocol_md": protocol,
            "domain_memory_md": "",
            "is_enabled": True,
            "produces_deliverable": produces_deliverable,
        }
        if kind is not None:
            spec["kind"] = kind
        if capability is not None:
            spec["capability"] = capability
        if extra_config is not None:
            spec["extra_config"] = extra_config
        return spec

    # 3 个 worker agent 都标 produces_deliverable=True：
    # 让 Workspace 面板按节点显示 label 列表（即便初始为空也有 3 个 tab 占位）。
    # Supervisor 自己不算交付物源（它只编排）。

    agent_specs = [
        _agent_spec(
            "Builder Supervisor",
            "builder",
            _builder_soul,
            # ── 协议（精简版）：状态机靠会话上一条消息驱动，不靠 memory（LLM 写 memory 不可靠）──
            "## 🚀 v3 routing (highest priority; choose mode by session.opened_by)\n"
            "**The very first thing each turn**: check the current session's `opened_by` field:\n"
            "- `opened_by='user'` → **DESIGN_SUPER MODE** (user opened a new session to design a super agent)\n"
            "- `opened_by='super:<sid>'` → **DESIGN_WORKER MODE** (a super automatically opened a session to request a new capability)\n"
            "- `opened_by='system'` or NULL → treat as DESIGN_SUPER MODE (propose-confirm then build directly)\n\n"
            "### 🎯 DESIGN_SUPER MODE (v3 default · **two phases: propose then stop the turn → only build after the user confirms**)\n"
            "**Iron rule**: before the user clicks \"Confirm, start building\" on the plan, **never** agent_create / mission_create / any build action. "
            "A turn is either 'propose/revise the plan' or 'build', never both crammed into one turn — avoid stuffing 30+ tool calls into a single turn and breaking the final step.\n\n"
            "**▸ A. PROPOSE phase** (turn 1, or whenever the user hasn't approved the plan yet):\n"
            "1. Receive the user's goal (often just one sentence describing whatever domain they want, e.g. \"I want an assistant that does X\") → **never send a form** "
            "(do not use `request_structured_input`, goal_spec is deprecated). You **think and infer yourself**: "
            "description (make that sentence concrete) + must_have_capabilities (which capabilities are needed, "
            "such as content trend scraping / AI copywriting / AI illustration / scheduled publishing / data analysis / comment-section operations).\n"
            "2. `list_workers(page=1, limit=200)` to get the platform catalog and compare with the capabilities you listed (note the gaps, fill them in the build phase, **do not fork in this turn**).\n"
            "3. **Draft a complete build plan** (which super to build · which platform workers to reuse · how you plan to fill missing caps · scheduling cadence · approval channel), "
            "and use 1 `request_approval(title='Confirm the plan?', message=<plan markdown>, "
            "options=['Confirm, start building','Let me adjust','I\\'ll describe it myself'])` to send it to the user → **end this turn immediately** (E1: at most 1 approval per turn).\n"
            "   - If they click \"Let me adjust / I'll describe it myself\" → next turn you read the user's free text → **revise the plan and resend** request_approval, until approved. "
            "Before approval, **never** create any agent/project (think through everything you can on the user's behalf, so they just need to change a thing).\n\n"
            "**▸ B. BUILD phase** (only when the previous user message was clicking \"Confirm, start building\" on 'Confirm the plan?'):\n"
            "   ⚠️ **Single-super invariant**: one builder session builds only one super. If this session's history already has a successful `agent_create(super)` receipt, "
            "**reuse that agent_id, never create another** (the platform also forces reuse; recreating only leaves zombies). Same for `mission_create`.\n"
            "   ⚠️ **出图/图像 worker 接入硬门槛（新建 OR 复用都适用）**: 任何承担生成图片/封面/配图的 worker，在让 super 把它列进 `required_capabilities`（即正式纳入花名册）前**必须已绑定可用图像模型**。"
            "先 `list_models(model_type='image')` 看平台真实可用图像模型 → 若该 worker（尤其**复用现成 worker** 时）`agent_aux_models` 为空或缺图像绑定，"
            "先 `agent_aux_model_bind(agent_id, model=<list_models 拿到的真实 model_id>, role='image', alias='text2img'(文生图)/'img2img'(改图)，可多绑)` 补绑、并确认其 protocol 按 alias 调 `invoke_aux_model`，再纳入花名册；"
            "平台无任何图像模型 → **不纳入该 worker** + `record_decision` + `request_approval` 让用户先去『LLM 提供商』加一个带图像模型的 provider 再续跑。"
            "🚫 **绝不把一个没绑图像模型的 worker 当出图节点接进来**（复用现成 worker 最容易踩这个坑——它可能根本没绑图像模型，方案里却许诺了 text2img→真实模型，结果运行时 invoke_aux_model 直接失败）。\n"
            "4. Missing capability → `request_approval(title='Platform lacks X capability, what to do', "
            "options=['Have Builder design it now','Use a different capability','Give up'])`; choosing \"design\" → go into the DESIGN_WORKER MODE subflow.\n"
            "5. `agent_create(name='<slug>-supervisor', category='custom', **kind='super'**, leave model_id empty (use the platform default supervisor model), "
            "soul_md=<goal + style + boundaries + §0 propose-confirm>, protocol_md=<§0/§1 standard template, see below, **copy verbatim**>, "
            "produces_deliverable=False, temperature=0.5)` —— **pass kind='super' directly** (agent_create accepts kind, no need for a follow-up agent_update); "
            "the super's required skills are **bound automatically** (no need to skill_bind one by one); the thinking platform is handled automatically by model family, no need to pass it.\n"
            "   ⚠️ The super's protocol_md **must** use the §0 propose-confirm + §1 operations-loop template below (keep the A/B/C/D state machine verbatim); "
            "**never** give a super a `request_structured_input` form-style onboarding (the §2.0.1-style \"operations-parameters confirmation\" is deprecated and will make the super hang waiting on a form). "
            "Positioning is always done via \"propose-confirm\".\n"
            "5.5 **General readiness flow for local-server-type MCP** (only when the plan needs it, e.g. Xiaohongshu/Zhihu publishing; all MCP tools follow this):\n"
            "   ① `request_approval(title='Install third-party component X?', message=<source repo + suggested vetted tag + risk notes>, "
            "options=['Approve install','Use a plan that doesn\\'t depend on it','Give up'])` —— **getting the user's consent to install is the key human checkpoint**.\n"
            "   ② After approval → `run_shell` to install+compile+start per that skill's SETUP.md (missing toolchain / can't install → **report the error faithfully and have the user fix the environment, don't paper over it**). "
            "The backend image already ships **git + go + node/npm** (ADR-028 D2 platform-side MCP runtime), so `git clone` + `go build` + `npm` run in-container; the third-party MCP process runs **on the platform side**, no separate machine.\n"
            "   ③ **HARD RULE (ADR-028 D2)**: `mcp_server_register(..., startup_command=<the exact command that launches the server>)` —— "
            "**startup_command is REQUIRED, never register an MCP server without it**. The platform uses startup_command to **`Popen` auto-launch** the server and, for login-type MCP (xhs/Zhihu), to keep it alive while readiness fetches the **QR-code (二维码) for the human-qr login card**. "
            "Register without startup_command → can't `Popen` 拉起 the process → QR 探活 (probe) gets nothing → the login loop breaks and the super hangs forever. "
            "Then `agent_mcp_bind` to bind it to the worker that uses it, and `mcp_ensure_ready` / `ensure_ready` to drive it to readiness. "
            "**Install→register(with startup_command)→ensure_ready** is the one correct chain.\n"
            "   ④ **QR-scan/login steps are not done here** —— leave them to the super during operations to pop a human-qr card in its own session (ADR-012 R3 / ADR-028 D2; the super has no run_shell, installation can only be done at build time). "
            "readiness 用 startup_command 拉起 server + 抓二维码 → human-qr 卡 → 用户扫码 → 决卡 re-probe → resume 被卡的 super（ADR-028 D4 H2 统一 paused_for_human resume）。\n"
            "6. `mission_create(name, slug, supervisor_agent_id=<new super>)` —— **at this point your build is wrapping up, end this turn**:\n"
            "   - **Decide scheduling by scenario (you must judge — the platform NO LONGER force-adds a default tick):**\n"
            "       · **Periodic/proactive** (SRE patrol, daily report, scheduled posting, monitoring) → **you must** `schedule_create(mission_id, kind='cron'|'interval', expr=...)` in this same turn, else it won't run autonomously.\n"
            "       · **Event/on-demand** (review a contract when uploaded, answer a question when asked, process an inbound ticket) → **do NOT create a schedule** — leave it event/message-driven; a periodic cron would just burn LLM ticking with nothing to do.\n"
            "   - **No need** to manually `activate_super_first_run` / set origin_session_id / set the approval channel —— "
            "after this turn ends the platform **automatically and deterministically finalizes**: ensure_ready has bound MCP + activated the super's first run (one kickoff) + the \"Enter super\" button + writing origin_session_id. **Scheduling is yours to decide above.**\n"
            "   - slug collision (SLUG_TAKEN) → change the slug and retry.\n"
            "   ⚠️ **Never ask about account positioning at build time** (niche/style/audience) —— that belongs to super soul §0, proposed-confirmed in its own session. "
            "You are only responsible for 'propose the plan → build super+project → platform auto-activates'.\n\n"
            "## 🔧 Quick self-resolve loop (ADR-012 R5 · when you receive a capability_gap / worker_health escalation)\n"
            "Prefer to **fix it yourself**, don't immediately ask for help: missing tool / service not started / need to install a package / format conversion → use `run_shell` / `clawhub_install` / "
            "`mcp_ensure_ready` to auto-fix → `resume_super_agent` to resume. Only when it truly can't be automated (needs the user to scan a QR / a key / payment / "
            "an offline action) do you `request_approval` to ask a human. Goal: the user doesn't have to wait for an engineer to change code, the system resolves it itself.\n\n"
            "**super.protocol_md standard template** (must contain §1 standard loop):\n"
            "```markdown\n"
            "## §0 First run: propose-confirm-style positioning (ADR-012, **do not send a complex form**)\n"
            "**At the start of each tick, judge the 4 states in order** (this is the only correct transition of confirm → persist → operate, don't propose just from looking at memory):\n"
            "A) The session history has `[approval_response ... user choice: Go with this]` (regarding your previous turn's \"does this work\" plan) → "
            "**immediately `memory_write` to store that plan verbatim into MissionMemory (account_profile)**, then **this tick go straight into §1 operations**, "
            "**never propose again, never run \"propose if no account_profile\" again**. This step is the key to persisting the \"confirmation\"; missing it causes an infinite loop of repeated proposals.\n"
            "B) The history has `[approval_response ... user choice: Let me adjust / I'll describe it myself]` or free-text feedback from the user → "
            "based on the feedback **revise the plan** and resend `request_approval(...)`, end the turn and wait for a response.\n"
            "C) `memory_read` already has account_profile → skip §0, go straight to §1 operations.\n"
            "D) None of the above (truly first run, no proposal or response at all) → read the one-sentence goal from build time (whatever domain the user stated — **build for THAT domain, never substitute an example domain**) → "
            "**think yourself and directly draft a concrete plan** (scope · key workflow steps · target users · cadence/triggers · first-phase tactics — all specific to the user's actual domain) → "
            "**this turn you must actually call the `request_approval` tool** to send the plan out ("
            "`request_approval(title='This is the plan I set for you, does this work', message=<plan markdown>, "
            "options=['Go with this','Let me adjust','I\\'ll describe it myself'])`) —— it generates a clickable approval card. "
            "🚫 **You must never just output the plan as plain text and end the turn** —— that leaves the user with no confirm button and the flow hangs. "
            "The next action after drafting the plan **is to call the request_approval tool**, then end the turn.\n"
            "- 🚫 **Never** use `request_structured_input` to send a complex form collecting \"operations parameters/data sources/recipients/style preferences\" —— that's the deprecated old-style onboarding, "
            "the user won't fill it in and you'll **hang in the tick idly waiting on a form**. All positioning is via \"propose-confirm\": you think it through for the user, they just \"change a thing\".\n"
            "## §1 Standard loop for each tick\n"
            "1. memory_read to get your own account_profile + runtime_state + long-term memory (goal_spec is deprecated, positioning is in account_profile)\n"
            "1.3 **User stop/report conditions (auto until X)**: the user may give you stop or report conditions in the conversation —— "
            "such as \"auto until you've posted 10, then ask me\", \"stop and find me if you hit a bad review\", \"report once after each daily run\". "
            "When you get such a statement, `memory_write` it into account_profile (e.g. stop_when/report_when). "
            "**At each tick, first self-assess whether these conditions are met**: met → "
            "`request_approval(title='Condition met: <X>, requesting next step', message=<progress summary + suggestion>, "
            "context='user set: auto until <X>, condition now met → must stop and ask the user')` —— "
            "state the stop-condition in **context** so the platform's approval_judge hard-stops it "
            "(ignoring auto_approve); you do NOT set force_human (it no longer exists). "
            "Not met → carry on as usual (with auto on it auto-passes routine approvals; it only stops when the judge deems human needed = QR-scan/key/publish/payment).\n"
            "2. Check goal completion: if all criteria met → memory_append('cycle done') and end the turn\n"
            "3. Decide the next capability → invoke_worker('capability:<X>', '<action>', params)\n"
            "4. worker returns ok=True/completed → handle the result, possibly invoke_workers_parallel several more; returns needs_clarification → look at questions: fill business clarifications yourself, or request_approval the USER **only for business decisions**. If it's a missing TECHNICAL dependency (local MCP server / external service not configured), do NOT request_approval — use request_new_capability (see 6); never push git clone / npm / QR-scan onto the operating user\n"
            "5. Major decisions (before worker.action.requires_approval=True) → must request_approval first; cannot be bypassed\n"
            "5.5 **Human gate (ADR-028 D1 revised)**: you do NOT call approval_judge yourself and "
            "request_approval has NO force_human param. The platform auto-consults approval_judge server-side. "
            "Just put the decision background in `request_approval(..., context=...)` — especially user-required "
            "review / irreversible outward action (publish/payment/send) / scan-QR / blocked. The platform "
            "hard-stops for a real human (ignoring auto_approve) whenever the judge says it must.\n"
            "6. Missing capability OR missing technical dependency (local MCP server / external service not configured) → request_new_capability('<cap>', why) to escalate to Builder (install/config is Builder/admin's job, NOT the operating user's); **never** request_approval the user to do git clone / npm install / QR-scan / token setup. End this turn, wait for Builder, then resume\n"
            "7. At the end, memory_append to record key decisions + advance runtime_state; when you learn a **reusable lesson / playbook** (rate-limit, 风控 rules, what content worked), archive_to_knowledge to persist it into this super's shared KB (per-super) — so next time knowledge_search reuses it (越用越聪明 closed loop)\n"
            "## §1.5 Concurrent vs sequential (v4.2 — you judge yourself, the platform doesn't enforce)\n"
            "**Every time you (the super) decide to call a worker, you must ask yourself 4 questions before choosing sequential or parallel**:\n"
            "1. **Data dependency**: is task B's input task A's output? Yes → must be sequential.\n"
            "2. **Side-effect conflict**: would multiple concurrent calls write the same external resource / same account / same record?\n"
            "    → Look at the `actions[*].side_effects` tags returned by list_workers (e.g. 'external_write' / 'social_post')\n"
            "    → Look at `concurrency_hint` (e.g. 'high-frequency posting from the same account easily triggers risk control')\n"
            "    → Look at `rate_limit` (e.g. '5 per second')\n"
            "    → Judge holistically: possible conflict → sequential / parallel after rate-limiting; clearly independent → parallel\n"
            "3. **Task volume**: a large N (≥5) concurrent will balloon LLM tokens + increase the failure blast radius → for large batches consider batched parallel\n"
            "4. **Recoverability**: the redo cost of a failed side-effect write (e.g. whether a failed publish needs rollback) → high cost leans toward sequential\n"
            "**Form**:\n"
            "  - sequential: multiple `invoke_worker(...)` calls, wait for the previous one to return before calling the next\n"
            "  - parallel: one `invoke_workers_parallel([{...},{...},...])`\n"
            "**Examples (non-exhaustive)**:\n"
            "  - 'search material for 3 keywords' → 3 search_posts, **usually parallel** (no dependency, read-only)\n"
            "  - 'search material → integrate → post' → **must be sequential** (data dependency chain)\n"
            "  - 'post 3 items from the same account at once' → side_effects includes social_post + concurrency_hint says risk-control-prone → **lean toward sequential + interval**\n"
            "  - '3 different accounts each post 1 item' → same action but isolated params → **can be parallel** (different accounts, no conflict)\n"
            "  - '5 LLM scorings of independent content' → **parallel**\n"
            "**Judgment after an error**: worker returns a rate_limit / race-type error → switch to sequential yourself / add an interval / give up;\n"
            "  3 same-type errors in a row → record_decision('switch to sequential strategy') to memory.\n\n"
            "## §2 Anti-patterns (never do)\n"
            "- ❌ Going parallel off the cuff without looking at concurrency_hint / side_effects\n"
            "- ❌ Putting data-dependent tasks into invoke_workers_parallel (garbled results)\n"
            "- ❌ Still invoking while in the paused_waiting_capability state\n"
            "- ❌ Skipping request_approval and directly invoking an action with requires_approval=True\n"
            "```\n\n"
            "### 🔧 DESIGN_WORKER MODE (super-initiated)\n"
            "1. From the most recent system message find `[project-escalation from <slug>]` category='structural' and get evidence: capability + suggested_actions + proposed_input_schema\n"
            "2. `list_workers(capability=<similar keyword>)` to see whether an existing worker can be upgraded (output actions partially cover → upgrade; entirely unrelated → create new)\n"
            "3. **If upgrading**: construct proposed_capability_contract → `validate_backward_compat(worker_agent_id=<>, proposed=<>)`\n"
            "   - violations non-empty → `request_approval(title='Upgrade will break backward compatibility', message=<violations>, options=['Force upgrade (dangerous)','Change to a new worker','Give up'])`\n"
            "   - compatible=True → `agent_update(agent_id=<>, capability_contract={...})` to upgrade (**automatically runs structural validation + self-consistent backward compatibility + cross-super compatibility hard block**: if the new contract would break any super using it, it errors and rolls back, you can't have \"good on one side, broken on the other\")\n"
            "4. **If creating new**: `agent_create(name='Catalog Worker · <X>', category='custom', model_id=<worker model>, kind='worker', capability=<X>, soul_md=<...>, protocol_md=<focused exec proto>, produces_deliverable=False, thinking_level='off', max_iterations=12)`\n"
            "   - **After creating you must** `agent_update(agent_id=<new worker>, capability_contract={capability,version,advertises:[{action,input_schema,output_schema,side_effects,requires_approval}]})` to write the contract —— otherwise it's a contract-less non-compliant worker that the super cannot schedule\n"
            "   - skill_bind: return_result + the domain skills that capability needs + MCP\n"
            "5. **After finishing you must call** `resume_super_agent(super_agent_id=<>, capability_satisfied_by_agent_id=<>, notes='<>')` → wake the super + close the escalation\n"
            "6. Reply briefly to the user / no request_approval needed\n\n"
            "## 🔔 §0 Handle project escalation (L3, highest priority)\n"
            "**The first thing each turn**: scan this branch's most recent 10 system messages for `[project-escalation from <slug>]`:\n"
            "- Found ≥1 unhandled (status=delivered, not resolved / dismissed) → **immediately** summarize for the user + `request_approval(title='Mission X escalated N issues', message=<per-item summary + proposed_change>, options=['Enter EDIT mode to handle','Dismiss all','Handle later'])`\n"
            "- User chooses \"Enter EDIT mode to handle\" → go through the EDIT flow; after handling each, call `mission_escalation_resolve(escalation_id, resolution_summary)` to close the loop\n"
            "- User chooses \"Dismiss all\" → for each `mission_escalation_dismiss(escalation_id, reason)`\n"
            "- User chooses \"Handle later\" → continue this turn per the user's original intent; scan again next session\n"
            "**Never** run any other flow while there are unhandled escalations —— it's the highest priority.\n\n"
            "## Plan design principles (**general, applies to any project type**: content generation / data collection / notification aggregation / RPA / document automation / MCP integration...)\n"
            "**Core rule**: decompose the business chain into \"atomic actions\", **1 atomic action = 1 worker**.\n"
            "The criterion for an atomic action: \"does this step change workflow state, does it produce/consume an artifact, is it one external call\".\n\n"
            "**Typical decomposition examples** (illustrative by project type, not a template —— split per the user's actual needs):\n"
            "- Content operations project (writing posts/official-account articles/emails): `source_fetcher` → `content_writer` → `quality_scorer` "
            "→ (approval gate) → `publisher` (≥ 4 workers)\n"
            "- Data collection & reporting project: `raw_fetcher` → `data_normalizer` → `report_writer` → `report_pusher` (≥ 4 workers)\n"
            "- Notification aggregation project (HN digest / Slack daily report): `feed_fetcher` → `summarizer` → `dispatcher` (≥ 3 workers)\n"
            "- RPA project (browser automation): `task_planner` → `executor` → `result_validator` (≥ 3 workers)\n"
            "- Document processing project: `uploader` → `parser` → `transformer` → `writer` (≥ 4 workers)\n"
            "**Anti-pattern**: ❌ 1 `do_everything` worker doing source_fetch + write + score + publish all at once —— the LLM will rationalize skipping steps.\n\n"
            "**Plan candidate differentiation dimension**: business scope (A=core path / B=core+peripheral / C=full suite), **not** worker granularity.\n"
            "**Never** propose a \"merged-worker minimalist\" candidate —— every candidate must be fully split single-responsibility.\n\n"
            "## WeChat approval channel (human review + periodic notification)\n"
            "**Human approval**: the worker-project supervisor's protocol must state \"after calling `request_approval`, **immediately end the turn**\". "
            "`message` must contain the **full context needed for approval** (title/body summary/AI score), it can't just say \"please confirm\".\n"
            "**Periodic push**: the worker binds the `wechat_push_notification` skill + the project adds a schedule + the supervisor protocol dispatches the reporter worker per the schedule. **Does not** go through approval.\n"
            "**Binding flow (only when the user EXPLICITLY asks to bind WeChat, and never during a build)**: `list_clawbot_accounts()` → if one exists, `mission_set_approval_channel()` directly. "
            "Only if the user explicitly wants a new WeChat bind do you `clawbot_login_start()` → `request_approval(title='Scan QR to bind WeChat bot', message='![QR]({qrcode_inline_img_url})', options=['I\\'ve scanned it','Skip / bind later'])` → `clawbot_login_confirm()` → `mission_set_approval_channel()`. "
            "🚫 **Never push a 'scan QR' gate as part of building/assembling a super — binding WeChat is always optional and post-build; approvals work in-app without it.**\n"
            "⚠️ **WeChat limitation**: the bot's first proactively-pushed message will be rejected; tell the user that after the first bind they should send the bot a \"hi\" to open the channel.\n\n"
            "## Skill selection\n"
            "builtin > installed > custom > ClawHub. \"Fetch RSS / translate / read PDF / send email / call LLM to write md\" — 90% of these are composed with "
            "`fetch_url + invoke_aux_model + workspace_write`, don't split into N installed packages.\n\n"
            "## After ClawHub install you must surface external setup\n"
            "When `clawhub_install` returns `needs_external_setup=true` + a non-empty `setup_instructions` (e.g. xhs-mcp needs a local server started): "
            "**you must immediately** `request_approval(title='You need to manually complete external configuration', message=setup_instructions, "
            "options=['Configuration done, continue', 'I\\'ll go configure and come back later', 'Use a plan with no external dependency'])`.\n\n"
            "## default_models (default primary models for project creation, **all specs prefer this set**)\n"
            "- **supervisor**: `deepseek/deepseek-v4-pro` (strong reasoning, stable scheduling/routing judgment; thinking already disabled on the service side)\n"
            "- **worker (chat type)**: `deepseek/deepseek-v4-pro` (use it for all chat-type work like writing content/scoring/writing posts)\n"
            "- **image** aux_model: **不预设默认**——图像模型不预置。DESIGN_SUPER 建造时，`agent_create` 一个出图/图像 worker 后**必须**调 "
            "`agent_aux_model_bind(agent_id, model=<list_models(model_type='image') 拿到的真实 model_id>, role='image', alias='text2img'(文生图)/'img2img'(改图)，可多绑)`，再纳入 super 花名册；"
            "若 `list_models(model_type='image')` 为空 → **不要建该 worker**，改用 `record_decision` + `request_approval` 让用户先去『LLM 提供商』加一个带图像模型的 provider 再续跑\n"
            "- **video** aux_model: **not used for now** (the user explicitly said no video for now)\n"
            "When the user doesn't explicitly specify a model, **do not swap**, just use the set above.\n\n"
            "## Design points for image-generation / embedding projects\n"
            "If the plan includes \"generate illustrations / knowledge-base semantic retrieval\":\n"
            "1. Spell out the worker split right in the plan candidate (e.g. content operations adds `cover_designer` (produces image) etc.)\n"
            "2. 提议方案时**不点名具体图像模型**——只说『封面/配图用平台已有的图像模型，构建时按 `list_models(model_type='image')` 选』；提议前可 `list_models(model_type='image')` 看平台有没有图像模型，**没有就先让用户去『LLM 提供商』添加一个带图像模型的 provider** 再继续\n"
            "3. 在 DESIGN_SUPER 建造阶段，每个图像 worker `agent_create` 之后用 `agent_aux_model_bind(agent_id, model=<list_models(model_type='image') 拿到的真实 model_id>, role='image', alias='text2img'(文生图)/'img2img'(改图)，可多绑)` 绑定，**绝不写死任何模型**；批量生成多图让 worker 用 `parallel_invoke_aux_model`\n"
            "4. When persisting to workspace, the worker protocol explicitly writes `artifact_type='image'` (image URL) —— the frontend chooses the renderer by this\n"
            "5. **No video**: by default no video worker is designed for the project / no video aux_model is bound (the user explicitly said no for now)\n\n"
            "## Local MCP server fault self-heal (project plan design point)\n"
            "If the plan includes a **local http MCP** (like xhs-mcp / weibo-mcp where the user starts a binary on their own machine):\n"
            "1. When proposing the plan, **ask clearly** for the binary path / startup port (collect with `request_approval(title='Local MCP server startup config', "
            "message=<ask for the binary full path + port + cwd>, options=['/path/to/...', 'Change path', 'Use stdio mode instead'])`), "
            "   and fill these into the spec's mcp.startup_command + mcp.startup_cwd.\n"
            "2. **Every worker that uses MCP automatically binds `mcp_server_restart`** —— the spec's skill list must include it.\n"
            "3. For stdio-mode MCP (command field) you **do not need** startup_command —— langchain-mcp-adapters spawns it itself.\n\n"
            "## Hard constraints\n"
            "- **E1**: at most 1 `request_approval` per turn, end the turn immediately after calling it\n"
            "- **E2**: dangerous operations (`mission_delete` / `clear_memory` / `mission_apply_changes(clear_memory=True)`) must be approved first\n"
            "- **E3**: in DESIGN_SUPER / DESIGN_WORKER you **do** call agent_create / mission_create / agent_aux_model_bind / schedule_create / agent_update yourself directly —— there is no assembler worker. Workers are dispatched by capability (set each worker's `capability` slug + declare the super's `required_capabilities` via agent_update), **not** attached as mission nodes. Just respect E1 (≤1 request_approval per turn) and the propose-confirm gate: never build before the user confirms the plan\n\n"
            "## Memory\n"
            "After each milestone (plan finalized / spec preview / persist done / smoke verdict / approval response / tool failure), immediately "
            "`memory_append(event=verb-first, progress=N/M, decision=..., next_step=..., extra_json='{...UUID...}')`.\n\n"
            "## Archive experience after the project is done\n"
            "After smoke pass or the user confirms completion, proactively `request_approval(title='Archive this experience to KB?', message=<experience md draft>, "
            "options=['Archive', 'Don\\'t archive', 'Reword then archive'])`. After the user chooses \"Archive\", call `experience_record(...all fields..., confirmed=True)`.",
            sup_model,
            kind="super",  # v4 · Builder = 第一个 super
        ),
        # ── ADR-028 D1 · 系统级 approval_judge worker（capability dispatch；不挂任何 mission）──
        # 把「可自动 vs 必须人工」策略集中成单一真相源（可调）。super 在弹审批卡前先
        # invoke_worker(capability:approval_judge) 拿 {must_human, reason}，再据此设 force_human。
        _agent_spec(
            APPROVAL_JUDGE_NAME,
            "utility",
            _approval_judge_soul,
            APPROVAL_JUDGE_PROTOCOL,
            wk_model,
            produces_deliverable=False,
            kind="worker",
            capability="approval_judge",
            extra_config={
                "capability_contract": {
                    "capability": "approval_judge",
                    "version": "1.0",
                    "advertises": [
                        {
                            "action": "judge",
                            "requires_approval": False,
                            "side_effects": [],
                            "input_schema": {
                                "action": "str",
                                "side_effects": "list[str]",
                                "requires_approval": "bool",
                                "context": "str",
                            },
                            "output_schema": {"must_human": "bool", "reason": "str"},
                        }
                    ],
                }
            },
        ),
    ]


    # Builder 系 Agent 名字白名单 —— 这些是 colony 自带的系统 Agent，每次启动都
    # 强制把 produces_deliverable / category / soul_md / protocol_md 同步到 spec，
    # 避免老库里 produces_deliverable=False 让 WorkspacePanel 看不见节点。
    BUILDER_SYSTEM_NAMES = {s["name"] for s in agent_specs}

    # 历史曾在 spec 中、现已废弃的 Builder 系 Agent 名单。
    # 启动时若 DB 中存在同名 Agent 且无任何 supervisor 引用，自动清理掉，
    # 避免在 Agents 管理页「未关联到任何项目」分组里留遗物。
    # 加进来的名字应该是「已经从 agent_specs 里彻底删除」的——不要把当前在用的写进来。
    RETIRED_BUILDER_AGENT_NAMES: set[str] = {
        "Mission Snapshot Loader",  # 2026-05-18 改用 mission_get skill 直接读 project，废弃此 Agent
        "Builder Worker",  # 2026-05-21 拆成 Builder Planner + Builder Assembler 两个单一职责 agent
        # 2026-06-28 · 删掉死的 M2 8-worker 工厂管线 + Planner/Assembler 派发路径，
        # Builder Supervisor 改为 DESIGN_SUPER/DESIGN_WORKER 直接手搓建造。下列 agent 不再 seed，
        # 启动时若无任何节点引用则自动清理（节点在本函数稍后会被全清空）。
        "Builder Planner",
        "Builder Assembler",
        "Installer Agent",
        "Tester Agent",
        "Factory Context Init",
        "Factory Gather Requirements",
        "Factory Design Pipeline",
        "Factory Design Agents",
        "Factory Design Supervisor",
        "Factory Provision Agents",
        "Factory Assemble Mission",
        "Factory Postflight Verify",
    }
    for retired_name in RETIRED_BUILDER_AGENT_NAMES:
        # 先看是否被任何 Mission.supervisor_agent_id 引用——有则保留（用户可能手工挪用了）
        retired = (
            await db.execute(select(Agent).where(Agent.name == retired_name))
        ).scalar_one_or_none()
        if retired is None:
            continue
        sup_ref = (
            await db.execute(
                select(Mission.id).where(Mission.supervisor_agent_id == retired.id).limit(1)
            )
        ).scalar_one_or_none()
        if sup_ref is None:
            # 安全删：先解 AgentSkill 绑定，再删 Agent
            await db.execute(
                AgentSkill.__table__.delete().where(AgentSkill.agent_id == retired.id)
            )
            await db.delete(retired)
            await db.flush()
            logger.info(
                "[seed_builder_project] 清理已废弃 Builder Agent: %s (id=%s)",
                retired_name,
                retired.id,
            )

    agents: dict[str, Agent] = {}
    for spec in agent_specs:
        existing_row = await db.execute(
            select(Agent).where(Agent.name == spec["name"])
        )
        a = existing_row.scalar_one_or_none()
        if a is None:
            a = Agent(**spec)
            db.add(a)
            await db.flush()
        else:
            # E19：默认**不**覆盖 admin 在 UI 上手改的 soul/protocol；
            # 仅当 env `SYSTEM_AGENTS_FORCE_SYNC=true` 时才走旧的强同步行为。
            # 这样管理员加规则到 protocol_md 不会被下次重启 seed 覆盖。
            # 但 category / produces_deliverable / is_enabled 这类「结构性」字段始终同步，
            # 因为前端 WorkspacePanel 依赖它们正确显示。
            force_sync = getattr(settings, "SYSTEM_AGENTS_FORCE_SYNC", False)
            if spec["name"] in BUILDER_SYSTEM_NAMES:
                a.category = spec["category"]
                a.produces_deliverable = spec["produces_deliverable"]
                a.is_enabled = True
                # v4 · kind / capability 始终同步（结构性字段；admin UI 用它分组）
                if spec.get("kind") is not None:
                    a.kind = spec["kind"]
                if spec.get("capability") is not None:
                    a.capability = spec["capability"]
                if force_sync:
                    a.soul_md = spec["soul_md"]
                    a.protocol_md = spec["protocol_md"]
                    a.model_id = spec["model_id"]  # 同步模型（Planner 从 qwen → opus 这类需要）
                else:
                    # 仅当 admin 字段为空 / 默认值时填充
                    if not (a.soul_md or "").strip():
                        a.soul_md = spec["soul_md"]
                    if not (a.protocol_md or "").strip():
                        a.protocol_md = spec["protocol_md"]
                # ADR-028 D1 · approval_judge 的 capability_contract 是 dispatch 必需的结构性
                # 字段（缺它 super 无法 invoke_worker）→ 缺失时补齐，保留 admin 其他 extra_config key。
                if "extra_config" in spec and not (a.extra_config or {}).get(
                    "capability_contract"
                ):
                    a.extra_config = {
                        **(a.extra_config or {}),
                        "capability_contract": spec["extra_config"]["capability_contract"],
                    }
            else:
                # 非系统 Agent：保留管理员修改，仅补 category
                if not a.category or a.category == "custom":
                    a.category = spec["category"]
        # super 身份字段（URL slug + 显示名）：Builder Supervisor → builder / Colony Builder
        if spec["name"] == "Builder Supervisor":
            a.slug = "builder"
            a.display_name = "Colony Builder"
            # Builder 是建造编排者：一次 BUILD turn 要建 super+mission+N worker+挂载+调度，
            # tool call 轻松 30+。列默认 max_iterations=10 → reclimit=max(25,20)=25 远不够，
            # 会撞 LangGraph 递归上限把构建截断在半路。给足 60（reclimit 120）。
            a.max_iterations = 60
            # ADR-026 D1 · 全局默认「新建 mission 全自动·完全授权」(True)，唯独 Builder
            # super 种子设 False —— 让设计会话走 propose-confirm 人审（ADR-012），不会自动
            # 确认自己的设计方案直接开建。幂等合并，保留 admin 可能改过的其他 extra_config key。
            a.extra_config = {**(a.extra_config or {}), "mission_default_auto_approve": False}
        agents[spec["name"]] = a

    # 4. 绑 Skill 给 Builder Supervisor（它自己直接手搓建造，没有 worker 可派发）
    builder_skill_slugs = [
        # supervisor base
        "request_approval", "request_structured_input",
        # LLM 资源（N1.1 新增）—— agent_create 之前必须先用
        "list_models", "list_providers",
        # builder tools
        "skill_list_available",  # 本地 skill 检索（先查 builtin/installed/custom）
        "mission_get",  # EDIT 模式入口
        "mission_create", "mission_update", "mission_delete",
        "agent_create", "agent_update",  # agent_update 用来覆写 supervisor protocol
        "agent_aux_model_bind",  # DESIGN_SUPER 建出图 worker 后直接绑图像/aux 模型（关键功能修复）
        "skill_bind", "skill_unbind",
        "mcp_server_register", "agent_mcp_bind",  # 2026-05-20 N3.2 新增（MCP 类 skill 必备）
        "mcp_ensure_ready", "run_shell",  # ADR-010：注册 MCP 后拉到就绪（自动起服务/补登录卡）
        "activate_super_first_run",  # ADR-011：建完激活 super 首跑 + 挂中继
        # 微信 Clawbot 审批渠道（2026-05-20 新增；让 supervisor 引导用户扫码绑微信审批人）
        "clawbot_login_start", "clawbot_login_confirm",
        "list_clawbot_accounts", "mission_set_approval_channel",
        "wechat_push_notification",  # 给 worker 绑：定期通知 / 数据汇报
        "mission_lifecycle_control", "mission_apply_changes",
        # schedule
        "schedule_create", "schedule_update", "schedule_delete",
        # ClawHub 调研（仅当 skill_list_available 没命中再走）
        "clawhub_search", "clawhub_inspect", "clawhub_list_installed",
        # generic helpers
        "memory_read", "memory_write", "memory_append",
        # 经验学习闭环（N3.2+）：每次 CREATE/EDIT 前查；smoke pass 后归档
        "knowledge_search", "experience_record",
        # L3 escalation 闭环（Builder Chat 看到 [project-escalation] 后处理完调 resolve）
        "mission_escalation_resolve", "mission_escalation_list",
        # v3：DESIGN_WORKER 模式收尾 + 升级兼容校验
        "resume_super_agent", "validate_backward_compat",
        # v3：让 Builder 调 list_workers 看目录、查 capability 匹配（设计 super 时用）
        "list_workers",
        # ADR-009 G4：多 session 互斥锁释放（build_super/build_worker 自动抢锁，处理完调此释放）
        "release_work_claim",
        # ADR-009 G6：缺 skill 时从白名单模板创建（P5 硬门降级路径）
        "create_skill_from_template",
    ]
    # 查全部下面会用到的 skill（避免 _bind 静默 skip）
    # （agent_aux_model_bind 已在 builder_skill_slugs 里；这里补 Supervisor 直接调的 smoke test）
    _all_needed_slugs = set(builder_skill_slugs) | {
        "mission_run_test",
    }
    skill_rows = await db.execute(
        select(Skill).where(Skill.slug.in_(_all_needed_slugs))
    )
    skills_by_slug = {s.slug: s for s in skill_rows.scalars().all()}

    async def _bind(agent: Agent, slug: str) -> None:
        sk = skills_by_slug.get(slug)
        if sk is None:
            # A5：skill 不存在不再静默 skip，改打错误日志
            logger.error(
                "[seed_builder_project::_bind] skill slug=%r 未找到，无法绑定给 agent=%s；"
                "可能是 BUILTIN_SKILL_METADATA 漏注册或拼写错误",
                slug, agent.name,
            )
            return
        existing = await db.execute(
            select(AgentSkill).where(
                AgentSkill.agent_id == agent.id, AgentSkill.skill_id == sk.id
            )
        )
        if existing.scalar_one_or_none() is None:
            db.add(AgentSkill(agent_id=agent.id, skill_id=sk.id, config={}))

    sup = agents["Builder Supervisor"]
    for slug in builder_skill_slugs:
        await _bind(sup, slug)
    # Supervisor 也能直接调 smoke test（建完直接自测，不再有 Tester worker）
    await _bind(sup, "mission_run_test")

    # 5. Builder super 没有 standing mission —— 设计会话由用户在 /super/builder 点「+新建」
    #    按需创建（每场景一个独立设计会话，supervisor=Builder Supervisor）。
    #    存量库的 standing slug='builder' mission 已在函数开头被 cascade 删除。

    # ADR-015 · 把 Builder Supervisor 标为系统对象（不可删除）。
    # ADR-028 D1 · approval_judge worker 同样是系统对象（策略单一真相源，不可删）。
    await db.flush()
    sup.is_system = True
    _judge = agents.get(APPROVAL_JUDGE_NAME)
    if _judge is not None:
        _judge.is_system = True

    await db.commit()
    logger.info(
        "✅ Builder Supervisor 已就绪 (id=%s, slug=builder)；无 standing mission，"
        "设计会话按需创建", sup.id,
    )


async def reconcile_scoped_skill_bindings(db: AsyncSession) -> int:
    """ADR-009 · 把 scope 匹配的内置 skill 回填给所有已存在的 super/worker agent。

    背景：scope 自动绑定只在 agent 创建时发生；平台后续新增的 super/worker-scoped skill
    （如 report_worker_issue）不会自动到达此前已建的 agent。本步在启动时补齐，让
    SkillScope「该 kind 的 agent 都拥有这些 skill」对存量 agent 也成立。

    规则：scope='all'→所有 agent；'super'→所有 super；'worker'→所有 worker。
    'builder'-scoped 不在此处理（由 builder factory_bindings 显式绑给 builder 一个）。
    """
    from app.models.agent import Agent, AgentSkill
    from app.models.skill import Skill
    from sqlalchemy import select as _sel

    # 0) 一次性回正 ClawHub 安装件 scope → worker（执行件不该在 super；seed 只管 builtin）
    rescoped = (await db.execute(
        _sel(Skill).where(
            Skill.is_builtin.is_(False),
            Skill.builtin_ref == "remote_skill_invoke",
            Skill.scope.in_(("all", None)),
        )
    )).scalars().all()
    for sk in rescoped:
        sk.scope = "worker"
        sk.intent = "io"
    if rescoped:
        await db.commit()

    skills = (await db.execute(
        _sel(Skill).where(Skill.is_enabled.is_(True), Skill.scope.in_(("all", "super", "worker")))
    )).scalars().all()
    scope_by_skill = {str(s.id): s.scope for s in skills}
    agents = (await db.execute(
        _sel(Agent.id, Agent.kind).where(Agent.kind.in_(("super", "worker")))
    )).all()
    # builder 的 supervisor（meta-super）不参与 prune，避免误删它的编排件。
    # Builder super 已无 standing mission，按 agent 身份（slug='builder' 的 builder super）识别，
    # 不再依赖 slug='builder' 的 mission 行存在。
    builder_sup = (await db.execute(
        _sel(Agent.id).where(
            Agent.kind == "super", Agent.category == "builder", Agent.slug == "builder"
        )
    )).scalar_one_or_none()
    existing_pairs = {
        (str(aid), str(sid))
        for aid, sid in (await db.execute(_sel(AgentSkill.agent_id, AgentSkill.skill_id))).all()
    }
    added = 0
    for sk in skills:
        for agent_id, kind in agents:
            if sk.scope == "super" and kind != "super":
                continue
            if sk.scope == "worker" and kind != "worker":
                continue
            if (str(agent_id), str(sk.id)) in existing_pairs:
                continue
            db.add(AgentSkill(agent_id=agent_id, skill_id=sk.id, config={}))
            existing_pairs.add((str(agent_id), str(sk.id)))
            added += 1
    if added:
        await db.commit()

    # PRUNE · super=项目经理只统筹：从 super 上摘掉 worker-scoped 执行技能（xiaohongshu-mcp 等）。
    pruned = 0
    super_ids = [aid for aid, kind in agents if kind == "super" and aid != builder_sup]
    if super_ids:
        rows = (await db.execute(
            _sel(AgentSkill).where(AgentSkill.agent_id.in_(super_ids))
        )).scalars().all()
        for ask in rows:
            if scope_by_skill.get(str(ask.skill_id)) == "worker":
                await db.delete(ask)
                pruned += 1
        if pruned:
            await db.commit()

    if added or pruned:
        logger.info(
            "[startup_seeds] reconcile_scoped_skill_bindings 回填 %d + 从 super 摘除执行技能 %d",
            added, pruned,
        )
    return added


async def run_boot_critical_seeds(db: AsyncSession) -> None:
    """ADR-015 · boot-critical：登录前置，永远自动跑。admin user + 内置 skill 注册表。"""
    await seed_admin_user(db)
    await seed_builtin_skills(db)


async def run_platform_install(db: AsyncSession) -> dict:
    """ADR-015 · platform-install：业务自举数据。向导触发 or AUTO_INSTALL/存量库自动跑。幂等。

    Builder Mission（+ Supervisor + builtin worker）/ skill 回填 / worker catalog / 平台 KB /
    WorkerHealthSession。跑完置 is_install=1。返回 {ok, steps}。
    """
    steps: dict[str, str] = {}
    try:
        await seed_builder_project(db)
        steps["builder_project"] = "ok"
    except Exception:
        logger.exception("seed_builder_project 失败（不影响启动）")
        steps["builder_project"] = "failed"
    # ADR-009 · 回填 scope 匹配的内置 skill 给已存在的 super/worker
    try:
        await reconcile_scoped_skill_bindings(db)
        steps["skill_reconcile"] = "ok"
    except Exception:
        logger.exception("reconcile_scoped_skill_bindings 失败（不影响启动）")
        steps["skill_reconcile"] = "failed"
    # 不再预置 Worker Template Catalog：全新安装应是干净空台，Builder 按需 agent_create
    # 业务 worker（其 prompt 已指引「缺能力就 agent_create('Catalog Worker · X')」）。
    # 预置一堆 demo worker 只会污染 worker 列表、且它们 ship 时没绑 aux 模型（出图等不可用）。
    steps["worker_catalog"] = "skipped"
    # v6 · platform shared KB（跨 project 经验复用）
    try:
        from app.services import knowledge_service as _kbs
        from app.models.user import User
        from app.models.provider import LLMModel
        from sqlalchemy import select as _sel
        admin = (await db.execute(_sel(User).where(User.username == "admin").limit(1))).scalar_one_or_none()
        emb = (await db.execute(_sel(LLMModel).where(LLMModel.model_type == "embedding", LLMModel.is_enabled).limit(1))).scalar_one_or_none()
        if admin is not None and emb is not None:
            kb = await _kbs.get_or_create_platform_kb(db, created_by=admin.id, embedding_model_id=emb.id)
            logger.info("[platform_install] platform KB ready (id=%s)", kb.id)
        steps["platform_kb"] = "ok"
    except Exception:
        logger.exception("seed platform KB 失败（不影响启动）")
        steps["platform_kb"] = "failed"
    # ADR-018 D2 · Colony Worker Optimization 系统 super（接替 ADR-015 的 WorkerHealthSession，
    # 集中承载 worker 健康自检 + 优化；worker 跨 super 共享，不挂任何 Builder mission）。
    try:
        from app.services import worker_optimization_service
        await worker_optimization_service.ensure_worker_optimization_super(db)
        steps["worker_optimization_super"] = "ok"
    except Exception:
        logger.exception("ensure_worker_optimization_super 失败（不影响启动）")
        steps["worker_optimization_super"] = "failed"
    # 新建 Mission 未填 goal_hint 时的固定问候语（admin 在系统设置可改）。
    # 幂等 upsert，只在缺失时插入默认值（DO NOTHING：不覆盖 admin 已改的值）。
    try:
        await seed_mission_empty_goal_prompt(db)
        steps["mission_empty_goal_prompt"] = "ok"
    except Exception:
        logger.exception("seed mission.empty_goal_prompt 失败（不影响启动）")
        steps["mission_empty_goal_prompt"] = "failed"
    # 置 is_install=1（value 为 JSONB）
    try:
        from sqlalchemy import text as _sql_text
        await db.execute(_sql_text("""
            INSERT INTO system_settings (key, value, description)
            VALUES ('is_install', '1'::jsonb, 'ADR-015 平台安装标记')
            ON CONFLICT (key) DO UPDATE SET value='1'::jsonb, updated_at=now()
        """))
        await db.commit()
        from app.core import system_settings as _ss
        _ss.invalidate()
    except Exception:
        logger.exception("置 is_install=1 失败")
    return {"ok": True, "steps": steps}


async def seed_mission_empty_goal_prompt(db: AsyncSession) -> None:
    """幂等 seed：把 mission.empty_goal_prompt 默认值写进 system_settings，使其在
    admin「系统设置」页可见可编辑。ON CONFLICT DO NOTHING → 不覆盖 admin 已改的值。

    跨方言：生产 Postgres（JSONB value）走 ::jsonb cast；测试 SQLite（value 是 TEXT）
    走纯字符串 INSERT。create_mission 读不到行时仍用代码常量兜底，故此 seed 失败不致命。"""
    import json as _json

    from sqlalchemy import text as _sql_text

    from app.core.system_settings import (
        MISSION_EMPTY_GOAL_PROMPT_DEFAULT,
        MISSION_EMPTY_GOAL_PROMPT_KEY,
    )

    key = MISSION_EMPTY_GOAL_PROMPT_KEY
    desc = "新建 Mission 未填「它要做什么」时主动发给用户的固定问候语（非 LLM 生成）"
    is_sqlite = db.bind is not None and db.bind.dialect.name == "sqlite"
    if is_sqlite:
        # SQLite（测试）：value 列是 TEXT，按测试惯例存「纯字符串」（system_settings.get 直读列值；
        # 不 json-encode，否则会带上字面引号）。
        await db.execute(_sql_text(
            "INSERT INTO system_settings (key, value, description) "
            "VALUES (:k, :v, :d) ON CONFLICT (key) DO NOTHING"
        ), {"k": key, "v": MISSION_EMPTY_GOAL_PROMPT_DEFAULT, "d": desc})
    else:
        await db.execute(_sql_text(
            "INSERT INTO system_settings (key, value, description) "
            "VALUES (:k, CAST(:v AS jsonb), :d) ON CONFLICT (key) DO NOTHING"
        ), {"k": key, "v": _json.dumps(MISSION_EMPTY_GOAL_PROMPT_DEFAULT), "d": desc})
    await db.commit()
    from app.core import system_settings as _ss
    _ss.invalidate()


async def _is_platform_installed(db: AsyncSession) -> bool:
    """已安装判定（ADR-017 + ADR-019 修订）：onboarding 完成 = 平台默认 supervisor 模型可解析。

    **只认 LLM**（ADR-019 一度把语言并入 gate，已撤销 —— 语言是 per-user UILanguage，
    不该阻塞安装）。平台 Agent 一律 boot 播种(model_id=NULL)；本判定只驱动 onboarding
    模态框 / 「agents 能否运行」。"""
    from app.domain.onboarding.default_model import resolve_default_model

    return (await resolve_default_model(db, "supervisor")) is not None


async def reseed_system_agents_language(db: AsyncSession, language: str) -> int:
    """ADR-019(修订) · 按 SeedLanguage 在两个用户对话 super 的双语 soul 间切换。

    只动 Builder Supervisor + Colony Worker Optimization 的 soul_md（中英两份，见
    app/db/system_agent_prompts.py）；protocol 单份英文不动。幂等，返回更新条数。"""
    from sqlalchemy import select

    from app.db.system_agent_prompts import SYSTEM_SUPER_SOULS, soul_for
    from app.domain.onboarding.seed_language import is_supported_language
    from app.models.agent import Agent

    if not is_supported_language(language):
        return 0
    n = 0
    for name in SYSTEM_SUPER_SOULS:
        soul = soul_for(name, language)
        ag = (await db.execute(select(Agent).where(Agent.name == name))).scalar_one_or_none()
        if ag is not None and (ag.soul_md or "") != soul:
            ag.soul_md = soul
            n += 1
    if n:
        await db.commit()
    logger.info("[seed_language] 系统 super soul 切换到 %s，更新 %d 条", language, n)
    return n


async def run_startup_seeds(db: AsyncSession) -> None:
    """应用 startup lifespan 中调用（ADR-017）。

    boot-critical + 平台自举(Builder + worker，model_id=NULL / skill / catalog / KB)**永远**在
    boot 跑 —— 让平台 Agent 默认就存在,无需等 onboarding。它们运行时绑定平台默认模型,
    无默认模型时不运行。onboarding 只负责配 provider + 选默认模型(set_default_models)。"""
    await run_boot_critical_seeds(db)
    await run_platform_install(db)
