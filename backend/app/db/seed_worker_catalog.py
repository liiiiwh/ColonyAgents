"""v3 · 平台 Worker Template Catalog 种子。

为新 super 调度提供的初始 11 个 capability-集中型 worker 模板。
每个模板 = agents 表一行（kind='worker', capability=<slug>, soul_md, protocol_md,
extra_config.capability_contract）+ 绑定相关 skill。

幂等：按 agent.name 反查；存在即只更新 capability / contract / kind（保护用户对 protocol 的修改）。

设计原则（R24 worker = 强落地）：
- enable_thinking=False（worker 直接做，不深思）
- max_iterations=12（避免空转）
- temperature=0.3（执行类需稳定）
- 绑 return_result 工具；不绑 super-only 工具（invoke_worker / request_approval 等）

capability_contract.advertises[*] 字段约定：
- action / input_schema / output_schema / since
- requires_approval (V27 平台审批门)
- v4.2 · 调度决策由 super LLM 自己做；以下字段是给 LLM 的「语义提示」，平台不据此加锁：
    · concurrency_hint: str        — 并发性提示（如 "同账号并发易触发风控；建议间隔 ≥30s"）
    · side_effects: list[str]      — 副作用标签（如 ["external_write","third_party_api","idempotent"]）
    · idempotent: bool             — 重复调同样参数是否安全
    · rate_limit: str              — 已知 rate limit（如 "≤10 次/分钟/账号"）
  super 在 list_workers 看到这些 hint，结合任务依赖自己决定 invoke 模式 +
  super 看错误后自己调整（重试 / 加间隔 / 改 sequential）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── 11 Worker Template 定义 ──
WORKER_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Catalog Worker · Content Writing",
        "capability": "content_writer",
        "description": "General-purpose text-and-image content writer: takes a topic + style guide, produces title / body / hashtags.",
        "soul_md": (
            "# Who I am\nI am the platform's shared content-writing worker.\n"
            "# Style\nPrecise; produce per the tone specified by super and the platform conventions; do not improvise on my own.\n"
            "# Boundaries\nWrite only, do not publish; if a factual claim has no source, proactively needs_clarification to ask super for grounding.\n"
        ),
        "protocol_md": (
            "## Input\n{topic, style_guide, target_length, grounding_sources(optional)}\n"
            "## Steps\n1. Validate input is complete; if key fields are missing (e.g. topic / style) → return_result(needs_clarification=True, "
            "clarification_questions=['what exactly is missing'])\n"
            "2. Write per style_guide → {title, body, tags}\n"
            "3. return_result(structured={title, body, tags}, text=<1-sentence summary>)\n"
            "## Constraints\nDo not fabricate specific numbers / rankings / historical events without source support; any numeric claim must go through grounding_sources.\n"
        ),
        "advertises": [
            {
                "action": "write_post",
                "input_schema": {"topic": "str", "style_guide": "str", "target_length": "int?", "grounding_sources": "list[str]?"},
                "output_schema": {"title": "str", "body": "str", "tags": "list[str]"},
                "requires_approval": False,
                "since": "1.0.0",
            }
        ],
        "skills": ["return_result", "memory_read", "fetch_url", "knowledge_search"],
    },
    {
        "name": "Catalog Worker · Quality Gate",
        "capability": "quality_gate",
        "description": "Fact-check + policy compliance + consistency LLM judgment; returns verdict.",
        "soul_md": (
            "# Who I am\nI am the platform's shared quality-gate worker, outputting a structured verdict.\n"
            "# Boundaries\nJudge only, do not modify content; a block must have evidence citing the upstream artifact.\n"
        ),
        "protocol_md": (
            "## Input\n{content, checks(list), grounding_sources, domain_hint}\n"
            "## Steps\n1. Validate content is non-empty → otherwise needs_clarification\n"
            "2. Call the output_quality_check tool (already bound skill)\n"
            "3. return_result(structured=verdict)\n"
        ),
        "advertises": [
            {
                "action": "check",
                "input_schema": {"content": "str", "checks": "list[str]", "grounding_sources": "list[str]?", "domain_hint": "str?"},
                "output_schema": {"verdict": "pass|warn|block", "issues": "list", "score": "float"},
                "requires_approval": False,
                "since": "1.0.0",
            }
        ],
        "skills": ["return_result", "output_quality_check"],
    },
    {
        "name": "Catalog Worker · Xiaohongshu Operations",
        "capability": "xhs_ops",
        "description": "Full-feature Xiaohongshu worker: search, post, comment, patrol, account data; goes through xhs-mcp.",
        "soul_md": (
            "# Who I am\nI am the platform's shared Xiaohongshu operations worker, interfacing with the Xiaohongshu API via xhs-mcp.\n"
            "# Boundaries\nExecute only when super explicitly requests and the action is compliant; posting actions requires_approval.\n"
        ),
        "protocol_md": (
            "## Input\nVaries by action; search_posts/keyword + filters; publish_note/{title,body,tags,image_url(s)}\n"
            "## Steps\n1. action='search_posts' → call search_feeds MCP → return_result(structured)\n"
            "2. action='publish_note' → prepare image (if none, placeholder via picsum) → call publish_content MCP → return_result(text='published', structured={note_id,url})\n"
            "3. action='patrol_comments' → list_feeds + get_feed_detail → return_result(structured=list of new comments)\n"
            "4. action='fetch_account' → user_profile MCP → return_result(structured)\n"
            "5. action='reply_comment' → reply_comment_in_feed MCP → return_result(text='replied')\n"
            "## Failure\nMCP timeout → return_result(ok=False, status='failed', error_msg); do not retry indefinitely\n"
        ),
        "advertises": [
            {"action": "search_posts",   "input_schema": {"keyword": "str", "filters": "dict?"},
             "output_schema": {"items": "list"}, "requires_approval": False, "since": "1.0.0"},
            {"action": "publish_note",   "input_schema": {"title": "str", "body": "str", "tags": "list[str]?", "image_url": "str?"},
             "output_schema": {"note_id": "str", "url": "str"}, "requires_approval": True,
             "side_effects": ["external_write","social_post"],
             "concurrency_hint": "High-frequency posting from the same account easily triggers risk control; recommend serial + interval ≥60s; with concurrency N≥3, likely to be rate-limited",
             "idempotent": False,
             "rate_limit": "Empirical value ~20 times/day/account",
             "since": "1.0.0"},
            {"action": "patrol_comments","input_schema": {"feed_ids": "list[str]?"},
             "output_schema": {"new_comments": "list"}, "requires_approval": False, "since": "1.0.0"},
            {"action": "fetch_account",  "input_schema": {"user_id": "str", "xsec_token": "str"},
             "output_schema": {"profile": "dict", "notes_recent": "list"}, "requires_approval": False, "since": "1.0.0"},
            {"action": "reply_comment",  "input_schema": {"feed_id": "str", "comment_id": "str", "content": "str", "xsec_token": "str"},
             "output_schema": {"ok": "bool"}, "requires_approval": True,
             "side_effects": ["external_write","social_reply"],
             "concurrency_hint": "Many replies from the same account in a short time are easily identified as spam/bots; recommend serial + interval ≥10s",
             "idempotent": False,
             "since": "1.0.0"},
        ],
        "skills": ["return_result", "memory_read", "fetch_url"],
        "needs_mcp": "xhs-mcp",
    },
    {
        "name": "Catalog Worker · Zhihu Operations",
        "capability": "zhihu_ops",
        "description": "Full-feature Zhihu worker placeholder; enrich advertises once the actual MCP is integrated.",
        "soul_md": "# I am the platform's shared Zhihu operations worker (placeholder implementation).\n# Boundaries\nCurrently no zhihu-mcp binding → any action results in needs_clarification.\n",
        "protocol_md": "## Steps\nOn receiving any action → return_result(needs_clarification=True, clarification_questions=['zhihu-mcp is not installed; please have super upgrade me or switch worker']).\n",
        "advertises": [
            {"action": "search_posts", "input_schema": {"keyword": "str"}, "output_schema": {"items": "list"},
             "requires_approval": False, "since": "0.1.0"},
        ],
        "skills": ["return_result"],
    },
    {
        "name": "Catalog Worker · Data Fetching",
        "capability": "data_fetcher",
        "description": "General-purpose fetch_url + parsing: HTML/JSON/RSS.",
        "soul_md": "# I am the platform's shared data-fetching worker.\n# Boundaries\nFetch only, do not cache; return raw + a brief parsed structure.\n",
        "protocol_md": (
            "## Input\n{url, parse_kind} (parse_kind: 'raw'/'json'/'html_main_text'/'rss_items')\n"
            "## Steps\n1. fetch_url(url) → text\n2. Parse per parse_kind\n3. return_result(text=<summary>, structured=<parsed>)\n"
        ),
        "advertises": [
            {"action": "fetch", "input_schema": {"url": "str", "parse_kind": "str"},
             "output_schema": {"text": "str", "parsed": "any"}, "requires_approval": False, "since": "1.0.0"},
        ],
        "skills": ["return_result", "fetch_url"],
    },
    {
        "name": "Catalog Worker · Topic Mining",
        "capability": "topic_picker",
        "description": "Picks topics from the knowledge base + real-time hot trends; per super's business direction.",
        "soul_md": "# I am the platform's shared topic-mining worker.\n# Boundaries\nOutput ≤10 candidate topics + a brief rationale.\n",
        "protocol_md": (
            "## Input\n{domain, style, count(default 5)}\n"
            "## Steps\n1. knowledge_search(domain) to retrieve historical successful experience\n2. Synthesize via LLM to generate N candidate topics\n"
            "3. return_result(structured={candidates: [{title, rationale, est_score}]})\n"
        ),
        "advertises": [
            {"action": "pick_topics", "input_schema": {"domain": "str", "style": "str?", "count": "int?"},
             "output_schema": {"candidates": "list"}, "requires_approval": False, "since": "1.0.0"},
        ],
        "skills": ["return_result", "knowledge_search", "fetch_url"],
    },
    {
        "name": "Catalog Worker · Content Scoring",
        "capability": "scorer",
        "description": "Multi-dimensional content scoring: title appeal / body readability / tag relevance / compliance.",
        "soul_md": "# I am the platform's shared content-scoring worker.\n# Boundaries\nJudge only, do not modify content; return a 0-10 score + per-dimension breakdown.\n",
        "protocol_md": (
            "## Input\n{content, dimensions(default ['title_hook','readability','tag_relevance','compliance'])}\n"
            "## Steps\nScore per dimension → overall score → return_result(structured={overall, per_dim, comments})\n"
        ),
        "advertises": [
            {"action": "score", "input_schema": {"content": "str", "dimensions": "list[str]?"},
             "output_schema": {"overall": "float", "per_dim": "dict", "comments": "str"},
             "requires_approval": False, "since": "1.0.0"},
        ],
        "skills": ["return_result"],
    },
    {
        "name": "Catalog Worker · Summarization",
        "capability": "summarizer",
        "description": "Long text / list data → short summary.",
        "soul_md": "# I am the platform's shared summarization worker.\n# Boundaries\nOutput a fixed length (target_chars ± 20%).\n",
        "protocol_md": "## Input\n{content, target_chars}\n## Steps\nLLM summarize → return_result(text=<summary>)\n",
        "advertises": [
            {"action": "summarize", "input_schema": {"content": "str", "target_chars": "int?"},
             "output_schema": {"summary": "str"}, "requires_approval": False, "since": "1.0.0"},
        ],
        "skills": ["return_result"],
    },
    {
        "name": "Catalog Worker · Data Reporting",
        "capability": "report_writer",
        "description": "Turns a metric dict → markdown data report; writes to super memory + pushes to wechat.",
        "soul_md": "# I am the platform's shared data-reporting worker.\n# Boundaries\nPurely generate markdown; do not make decisions on my own; pushing is decided by super.\n",
        "protocol_md": (
            "## Input\n{metrics(dict), date_range, audience(str)}\n"
            "## Steps\nGenerate a markdown report (title + key-metrics table + trend observations) → return_result(text=<markdown>)\n"
        ),
        "advertises": [
            {"action": "write_report", "input_schema": {"metrics": "dict", "date_range": "str?", "audience": "str?"},
             "output_schema": {"report_md": "str"}, "requires_approval": False, "since": "1.0.0"},
        ],
        "skills": ["return_result"],
    },
    {
        "name": "Catalog Worker · Notification Push",
        "capability": "broadcaster",
        "description": "WeChat / email notifications; sent under super's scheduling. requires_approval.",
        "soul_md": "# I am the platform's shared notification-push worker.\n# Boundaries\nPush only the content provided by super; do not modify content.\n",
        "protocol_md": (
            "## Input\n{channel(wechat/email), recipients(list), title, content}\n"
            "## Steps\nchannel='wechat' → wechat_push_notification skill; channel='email' → return_result(needs_clarification=True, ['email channel not implemented'])\n"
        ),
        "advertises": [
            {"action": "broadcast", "input_schema": {"channel": "str", "recipients": "list[str]", "title": "str", "content": "str"},
             "output_schema": {"sent_count": "int"}, "requires_approval": True,
             "side_effects": ["external_write","notification"],
             "concurrency_hint": "The wechat channel has a 5 times/sec/account limit; with concurrency N>5, mind batching",
             "idempotent": False,
             "rate_limit": "5 times/sec/clawbot account",
             "since": "1.0.0"},
        ],
        "skills": ["return_result", "wechat_push_notification"],
    },
    {
        "name": "Catalog Worker · Image Generation",
        "capability": "image_designer",
        "description": "Calls aux_model image to generate images; auto-uploads to S3 then returns the URL.",
        "soul_md": "# I am the platform's shared image-generation worker.\n# Boundaries\nGenerate images per the prompt only; do not modify the prompt given by super.\n",
        "protocol_md": (
            "## Input\n{prompt, size?, aspect_ratio?}\n"
            "## Steps\n1. invoke_aux_model(role='image', input=prompt) → get the image URL (litellm auto-mirrors to S3)\n"
            "2. return_result(artifact_url=<url>, media_type='image/png', text='generated')\n"
        ),
        "advertises": [
            {"action": "generate", "input_schema": {"prompt": "str", "size": "str?", "aspect_ratio": "str?"},
             "output_schema": {"artifact_url": "str"}, "requires_approval": False, "since": "1.0.0"},
        ],
        "skills": ["return_result", "invoke_aux_model"],
    },
]


async def seed_worker_template_catalog(db: AsyncSession) -> int:
    """种子 11 个 capability-集中型 worker 模板。返回新建条数。

    ADR-017：worker 一律以 model_id=NULL 播种 —— 运行时解析平台默认 agent 模型;
    无默认模型时不运行(不再因没配模型而跳过 seed)。"""
    from app.models.agent import Agent, AgentSkill
    from app.models.skill import Skill

    # 批量查 skills
    all_slugs = {s for t in WORKER_TEMPLATES for s in t["skills"]}
    skill_rows = (await db.execute(select(Skill).where(Skill.slug.in_(list(all_slugs))))).scalars().all()
    skill_by_slug = {s.slug: s for s in skill_rows}

    created = 0
    for tpl in WORKER_TEMPLATES:
        # idempotent 按 name 反查
        existing = (await db.execute(select(Agent).where(Agent.name == tpl["name"]))).scalar_one_or_none()
        capability_contract = {
            "capability": tpl["capability"],
            "version": "1.0.0",
            "advertises": tpl["advertises"],
            "deprecated_actions": [],
        }
        if existing is None:
            agent = Agent(
                name=tpl["name"],
                category="custom",
                kind="worker",
                capability=tpl["capability"],
                model_id=None,  # ADR-017 · 运行时绑定平台默认 agent 模型
                soul_md=tpl["soul_md"],
                protocol_md=tpl["protocol_md"],
                description=tpl["description"],
                max_iterations=12,
                temperature=0.3,
                produces_deliverable=False,  # v3 worker 不写 workspace artifact
                enable_thinking=False,
                extra_config={"capability_contract": capability_contract},
            )
            db.add(agent)
            await db.flush()
            # bind skills
            for slug in tpl["skills"]:
                sk = skill_by_slug.get(slug)
                if sk is None:
                    logger.warning("[seed_worker_catalog] skill %s 不存在，跳过绑给 %s", slug, tpl["name"])
                    continue
                db.add(AgentSkill(agent_id=agent.id, skill_id=sk.id, config={}))
            created += 1
            logger.info("[seed_worker_catalog] 创建 %s (capability=%s)", tpl["name"], tpl["capability"])
        else:
            # 已存在 → 仅刷新 kind/capability/contract，不动 user 改过的 soul/protocol
            existing.kind = "worker"
            existing.capability = tpl["capability"]
            existing.extra_config = {
                **(existing.extra_config or {}),
                "capability_contract": capability_contract,
            }
    # v4.1 · 始终 commit：existing 路径也要把新的 capability_contract（含 parallel_safe）落库
    await db.commit()

    # v6 · 同步刷新 worker_capability_actions 索引（让 find_workers 能查到 catalog workers）
    try:
        from app.domain.builder.capability_index import rebuild_for_worker
        # 拿所有 kind='worker' 的 agent_id（catalog 11 个 + 自定义）
        from sqlalchemy import select as _sel
        from app.models.agent import Agent
        worker_ids = (await db.execute(
            _sel(Agent.id).where(Agent.kind == "worker", Agent.is_enabled.is_(True))
        )).scalars().all()
        for wid in worker_ids:
            try:
                await rebuild_for_worker(db, worker_agent_id=wid)
            except Exception:
                logger.exception("[seed_worker_catalog] rebuild_for_worker %s 失败 (不阻塞)", wid)
    except Exception:
        logger.exception("[seed_worker_catalog] capability_index batch rebuild 失败 (不阻塞)")

    return created
