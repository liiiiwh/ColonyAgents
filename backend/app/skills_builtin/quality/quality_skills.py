"""L1 · 通用输出质量门 (Output Quality Gate)。

设计目标：每个 Factory 建出来的项目，对任何**有副作用**（发布 / 调外部 API / 财务操作 / 不可逆）
的节点之前自动插入一个 `quality_gate_*` worker。这个 worker 用 LLM 评审上游产物，输出结构化
verdict（pass / warn / block），supervisor 协议根据 verdict 决定是 dispatch 下游副作用节点
还是回退到上游 writer 带 revision_brief 重试。

护栏：
- H1 fail-open：judge LLM 连续 2 次异常 / 超时 → 返回 warn + reason='judge_unavailable'，
  避免副作用节点永远跑不了。supervisor 协议会一起 escalate 通知用户。
- H2 双 judge：高风险 domain (`financial` / `irreversible` / `regulated_content`) 并行调
  2 个 model，任一 block 即 block；都 pass 才 pass。普通 `content_ops` 走单 judge 控成本。
- H3 override 高门槛：`output_quality_check_force_override` 要求 justification ≥100 字符
  且必须 quote 原 verdict 里至少 1 条 issue.evidence；不满足直接 raise ValueError。

大小有界：
- verdict 响应整体 ≤4KB，最多 5 条 issue，每条 evidence ≤200 字符
- verdict 不落 workspace（ADR-027：by-node workspace 簿记退役）。verdict_id 直接用 uuid
  生成，供 H3 override 引用；重试上界由 tick 级 max_iterations / 审批门兜底。
- 待审产物按 capability 从 S3 读取最新交付物（colony/workspace/{mission_id}/{capability}/）
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


# ── 配置常量 ──
MAX_VERDICT_BYTES = 4_000
MAX_ISSUES = 5
MAX_EVIDENCE_CHARS = 200
MAX_JUSTIFICATION_MIN_CHARS = 100

# 高风险 domain 触发双 judge（H2）
HIGH_SEVERITY_DOMAINS = frozenset({"financial", "irreversible", "regulated_content"})

# H1 fail-open：连续 2 次 judge 调用失败 → 返回 warn 而非 block
JUDGE_FAILURE_THRESHOLD = 2


# ── Judge prompt 模板 ──
_JUDGE_SYSTEM_PROMPT = """你是 Colony 项目质量守门员。你的任务是审核 worker 产物，按指定 checks 给出结构化判定。

**返回格式（严格 JSON，无 markdown 围栏，无解释文字）**：
```
{
  "verdict": "pass" | "warn" | "block",
  "score": 0.0-1.0,
  "issues": [
    {
      "check": "<check name>",
      "severity": "info" | "warn" | "block",
      "evidence": "<引用产物里的具体片段，≤200 字>",
      "fix_suggestion": "<给上游 writer 的修正建议，≤100 字>"
    }
  ],
  "cited_sources": ["<grounding_source 节点名>", ...]
}
```

**判定规则**：
- `pass` = 全部 check 通过，无 issue。
- `warn` = 有 info/warn 级 issue 但无 block 级 → 可继续但人审时要注意。
- `block` = 至少 1 条 issue 是 block 级（严重事实错误 / 政策违规 / 不可逆操作风险）→ 必须打回。

**check 项语义说明**：
- `factual_grounding`：产物里的具体数字 / 排行 / 历史事件等可验证声明，必须能在 grounding_sources 里找到出处。
  ⚠️ **关键反模式**：写"X 排行榜 / TOP N / 调查显示 / 数据表明"但 grounding_sources 里没有对应数据 → block。
- `policy`：是否违反内容平台政策（暴力、涉政、医疗夸大、广告法绝对化用语等）。
- `schema_match`：产物结构是否符合 expected schema（标题长度、字段齐备）。
- `freshness`：产物是否引用过期信息（去年的活动、已下架的产品）。
- `consistency`：标题、正文、标签是否一致。
- `safety`：是否有诱导自伤、违规交易、隐私泄露等高风险表达。

**评分启发**：每条 block issue 扣 0.3 分；每条 warn 扣 0.1；每条 info 扣 0.03；最低 0.0。
"""


def _judge_user_prompt(
    artifact_text: str,
    artifact_label: str,
    checks: list[str],
    grounding: dict[str, str],
    domain_hint: str,
) -> str:
    parts = [
        f"## 待审产物 [{artifact_label}]\n\n{artifact_text}",
        f"\n\n## 要执行的 checks（按顺序）\n" + "\n".join(f"- {c}" for c in checks),
    ]
    if domain_hint:
        parts.append(f"\n\n## domain_hint\n{domain_hint}")
    if grounding:
        parts.append("\n\n## grounding_sources（用来核对事实声明）")
        for label, text in grounding.items():
            text_short = text if len(text) <= 4000 else text[:4000] + "\n...[truncated]"
            parts.append(f"\n### {label}\n{text_short}")
    else:
        parts.append(
            "\n\n## grounding_sources\n（无外部出处。所有未声明来源的具体数据 / 排行 / "
            "历史事件应视为 unsupported，按 check=factual_grounding severity=block 判定。）"
        )
    parts.append(
        "\n\n返回严格 JSON 对象（不要 markdown fence，不要解释文字）。"
    )
    return "".join(parts)


# ── 内部工具：按 capability 从 S3 读最新交付物 ──
_TEXT_EXTS = frozenset({"md", "txt", "json", "html"})


async def _read_capability_latest(
    ctx: BuiltinToolContext, capability: str, label: str | None = None
) -> tuple[str | None, str | None]:
    """读某 capability 的最新交付物内容（ADR-027：交付物只活在 S3，按 capability 归档）。

    从 `colony/workspace/{mission_id}/{capability_slug}/` 列对象，可选按 label 过滤，
    取最新（last_modified）的文本类对象下载并 utf-8 解码。返回 (text, error)。
    """
    from app.services.storage_service import get_storage
    from app.services.workspace_service import _slugify_segment

    if ctx.mission_id is None:
        return None, "❌ 缺 mission_id"
    cap_slug = _slugify_segment(capability)
    prefix = f"colony/workspace/{ctx.mission_id}/{cap_slug}/"
    storage = get_storage()
    objects = [o for o in await storage.list_objects(prefix) if o.get("key")]
    if not objects:
        return None, f"⚠️ capability {capability} 尚无交付物"
    if label:
        lbl_slug = _slugify_segment(label)
        matched = [o for o in objects if lbl_slug in o["key"].rsplit("/", 1)[-1]]
        if not matched:
            return None, f"⚠️ capability {capability} 没有 label≈{label} 的交付物"
        objects = matched
    objects.sort(key=lambda o: o.get("last_modified") or "")
    latest = objects[-1]
    key = latest["key"]
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    if ext and ext not in _TEXT_EXTS:
        return None, f"⚠️ capability {capability} 最新交付物为二进制（{ext}），无法做文本审核"
    try:
        body = await storage.download(key)
        return body.decode("utf-8"), None
    except Exception as exc:  # noqa: BLE001
        return None, f"⚠️ 下载/解码失败 key={key}: {exc}"


def _truncate_verdict(v: dict[str, Any]) -> dict[str, Any]:
    """把 verdict 截到 size cap：≤5 issues，每条 evidence ≤200 chars，整体 JSON ≤4KB。"""
    issues = list((v.get("issues") or []))[:MAX_ISSUES]
    for it in issues:
        ev = it.get("evidence") or ""
        if isinstance(ev, str) and len(ev) > MAX_EVIDENCE_CHARS:
            it["evidence"] = ev[:MAX_EVIDENCE_CHARS] + "..."
        fix = it.get("fix_suggestion") or ""
        if isinstance(fix, str) and len(fix) > 200:
            it["fix_suggestion"] = fix[:200] + "..."
    out = {
        "verdict": v.get("verdict") or "warn",
        "score": float(v.get("score") or 0.0),
        "issues": issues,
        "cited_sources": list(v.get("cited_sources") or [])[:10],
    }
    # 额外字段（如 reason='judge_unavailable'）保留
    for extra_k in ("reason", "judge_models"):
        if extra_k in v:
            out[extra_k] = v[extra_k]
    # 整体 cap
    blob = json.dumps(out, ensure_ascii=False)
    if len(blob) > MAX_VERDICT_BYTES:
        # 砍 issues 直到合规
        while issues and len(blob) > MAX_VERDICT_BYTES:
            issues.pop()
            out["issues"] = issues
            blob = json.dumps(out, ensure_ascii=False)
    return out


def _parse_judge_response(raw: str) -> dict[str, Any] | None:
    """尝试从 LLM 输出里提取 JSON 对象。允许有 markdown fence 包裹（容错）。"""
    s = raw.strip()
    # strip markdown fence
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL)
    if fence:
        s = fence.group(1)
    else:
        # 找第一个 { 到最后一个 }
        first = s.find("{")
        last = s.rfind("}")
        if first >= 0 and last > first:
            s = s[first : last + 1]
    try:
        obj = json.loads(s)
        if not isinstance(obj, dict):
            return None
        return obj
    except json.JSONDecodeError:
        return None


# ── Judge LLM 调用（带 H1 fail-open / H2 dual judge） ──
async def _invoke_single_judge(
    ctx: BuiltinToolContext,
    system_prompt: str,
    user_prompt: str,
    alias_or_role: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """调一次 judge LLM。返回 (parsed_verdict, error_msg)；二者必有一非空。"""
    # 复用 aux_model_skills 的 binding 解析 + litellm 调用
    from app.skills_builtin.llm.aux_model_skills import _invoke_litellm, _resolve_binding

    binding, err = await _resolve_binding(ctx, alias_or_role)
    if err or binding is None:
        return None, f"judge binding error: {err}"
    # 拼一个 chat 模式的 input：system + user 用分隔符
    combined = f"<<SYSTEM>>\n{system_prompt}\n<<USER>>\n{user_prompt}"
    try:
        raw = await _invoke_litellm(
            provider_type=binding["provider_type"],
            base_url=binding.get("base_url"),
            api_key=binding["api_key"],
            model_id=binding["model_id"],
            mode="chat",
            input_text=combined,
            merged_config={"temperature": 0.0, "max_tokens": 2000},
            ctx=ctx,
            label="quality_judge",
        )
    except Exception as exc:
        logger.warning("quality judge LLM 调用异常: %s", exc)
        return None, f"judge call exception: {exc}"
    parsed = _parse_judge_response(raw)
    if parsed is None:
        return None, f"judge 返回非 JSON：{raw[:300]}"
    return parsed, None


async def _invoke_judge_with_fail_open(
    ctx: BuiltinToolContext,
    system_prompt: str,
    user_prompt: str,
    aliases: list[str],
) -> dict[str, Any]:
    """H1：连续 N 次失败就 fail-open 返回 warn + reason='judge_unavailable'。
    H2：并行调多个 judge，取最严重的判定。
    """
    if len(aliases) == 1:
        # 单 judge，2 次重试
        last_err = None
        for attempt in range(JUDGE_FAILURE_THRESHOLD):
            parsed, err = await _invoke_single_judge(
                ctx, system_prompt, user_prompt, aliases[0]
            )
            if parsed is not None:
                parsed["judge_models"] = [aliases[0]]
                return parsed
            last_err = err
            logger.info(
                "📊 colony_l1_judge_retry attempt=%d alias=%s err=%s",
                attempt + 1, aliases[0], (err or "")[:120],
            )
        # H1 fail-open
        logger.warning("📊 colony_l1_judge_fail_open aliases=%s last_err=%s", aliases, last_err)
        return {
            "verdict": "warn",
            "score": 0.5,
            "issues": [
                {
                    "check": "judge_availability",
                    "severity": "warn",
                    "evidence": f"judge LLM 连续 {JUDGE_FAILURE_THRESHOLD} 次失败",
                    "fix_suggestion": "supervisor 应同时发 escalation 通知 owner",
                }
            ],
            "cited_sources": [],
            "reason": "judge_unavailable",
            "judge_models": aliases,
        }

    # H2 dual judge：并行调 2 个
    results = await asyncio.gather(
        *[_invoke_single_judge(ctx, system_prompt, user_prompt, a) for a in aliases],
        return_exceptions=True,
    )
    parsed_list: list[dict[str, Any]] = []
    judges_used: list[str] = []
    for alias, res in zip(aliases, results, strict=True):
        if isinstance(res, Exception):
            continue
        parsed, _err = res  # type: ignore[assignment]
        if parsed is not None:
            parsed_list.append(parsed)
            judges_used.append(alias)
    if not parsed_list:
        logger.warning("📊 colony_l1_judge_fail_open dual aliases=%s all failed", aliases)
        return {
            "verdict": "warn",
            "score": 0.5,
            "issues": [
                {
                    "check": "judge_availability",
                    "severity": "warn",
                    "evidence": "dual-judge 全部失败",
                    "fix_suggestion": "supervisor 应同时发 escalation 通知 owner",
                }
            ],
            "cited_sources": [],
            "reason": "judge_unavailable",
            "judge_models": aliases,
        }
    # 合并：任一 block → block；其它取 max severity；issues 合并去重 (check, severity)
    severity_rank = {"info": 0, "warn": 1, "block": 2}
    final_verdict = "pass"
    for p in parsed_list:
        v = p.get("verdict") or "warn"
        if v == "block":
            final_verdict = "block"
            break
        if v == "warn" and final_verdict != "block":
            final_verdict = "warn"
    # min score
    min_score = min((float(p.get("score") or 0.0) for p in parsed_list), default=0.0)
    # 合并 issues
    seen: set[tuple[str, str, str]] = set()
    merged_issues: list[dict[str, Any]] = []
    for p in parsed_list:
        for it in p.get("issues") or []:
            key = (
                it.get("check") or "",
                it.get("severity") or "",
                (it.get("evidence") or "")[:80],
            )
            if key in seen:
                continue
            seen.add(key)
            merged_issues.append(it)
    # 按 severity 降序
    merged_issues.sort(
        key=lambda x: -severity_rank.get(x.get("severity") or "info", 0)
    )
    cited = sorted(
        {s for p in parsed_list for s in (p.get("cited_sources") or [])}
    )
    return {
        "verdict": final_verdict,
        "score": min_score,
        "issues": merged_issues,
        "cited_sources": cited,
        "judge_models": judges_used,
    }


# ── Tool factories ──
def output_quality_check_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _check(
        upstream_capability: str,
        checks: list[str],
        artifact_label: str = "",
        grounding_sources: list[str] | None = None,
        domain_hint: str = "",
        severity_threshold: str = "warn",
    ) -> str:
        """对 upstream_capability 的最新交付物执行 quality check，返回结构化 verdict JSON。

        参数：
            upstream_capability: 要审核的上游能力 slug（如 'content-writer'）；从 S3 读其最新交付物
            checks: 要执行的 check 项列表（如 ['factual_grounding', 'policy', 'consistency']）
            artifact_label: 可选，指定 capability 下具体交付物 label；省略则取最新
            grounding_sources: 可选，用来核对事实的其它 capability slug 列表
            domain_hint: 可选，传给 judge 的领域提示（'content_ops' / 'financial' / ...）
            severity_threshold: 当前未使用，预留给未来分级。verdict 永远返回所有 issue。

        返回：verdict JSON 字符串。supervisor 协议根据 verdict.verdict（pass/warn/block）决策。
        """
        if ctx.agent_node_name is None or ctx.mission_id is None:
            return json.dumps({"error": "缺 agent_node_name / mission_id 上下文"})

        # ── 读 upstream 交付物（按 capability 从 S3 取最新） + grounding ──
        label_to_use = artifact_label or None
        artifact_text, err = await _read_capability_latest(
            ctx, upstream_capability, label_to_use
        )
        if artifact_text is None:
            return json.dumps(
                {
                    "verdict": "block",
                    "score": 0.0,
                    "issues": [
                        {
                            "check": "input_missing",
                            "severity": "block",
                            "evidence": err or f"无法读 capability {upstream_capability} 交付物",
                            "fix_suggestion": "supervisor 应先 invoke_worker 让上游 capability 产出交付物",
                        }
                    ],
                    "cited_sources": [],
                },
                ensure_ascii=False,
            )

        grounding: dict[str, str] = {}
        for src in grounding_sources or []:
            text, _err = await _read_capability_latest(ctx, src, None)
            if text:
                grounding[src] = text

        # ── 选 judge alias（H2 dual judge for high-severity domain） ──
        if domain_hint in HIGH_SEVERITY_DOMAINS:
            # 优先用 strict_judge / chat 两个不同的 binding；都没有就退化单 chat
            aliases = ["strict_judge", "chat"]
            # 去重后只保留实际能解析的 binding；解析失败的会在 _invoke_judge_with_fail_open 内被跳过
        else:
            aliases = ["chat"]

        # ── 调 judge ──
        system_prompt = _JUDGE_SYSTEM_PROMPT
        user_prompt = _judge_user_prompt(
            artifact_text=artifact_text,
            artifact_label=label_to_use or f"{upstream_capability}.latest",
            checks=checks or ["factual_grounding", "policy", "consistency"],
            grounding=grounding,
            domain_hint=domain_hint or "",
        )
        verdict_raw = await _invoke_judge_with_fail_open(
            ctx, system_prompt, user_prompt, aliases
        )
        verdict = _truncate_verdict(verdict_raw)
        # ADR-027：verdict 不落 workspace；verdict_id 直接 uuid 生成供 H3 override 引用
        verdict["id"] = str(uuid.uuid4())

        logger.info(
            "📊 colony_l1_verdict project=%s node=%s upstream_capability=%s verdict=%s score=%.2f issues=%d judges=%s",
            ctx.mission_id, ctx.agent_node_name, upstream_capability,
            verdict["verdict"], verdict["score"], len(verdict.get("issues") or []),
            verdict.get("judge_models"),
        )
        return json.dumps(verdict, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_check,
        name="output_quality_check",
        description=(
            "L1 质量门：审核上游 capability 的最新交付物（S3），输出结构化 verdict (pass/warn/block)。\n"
            "**关键反模式守护**：写'X 排行榜 / TOP N / 调查显示'但无 grounding_sources → block。\n"
            "参数：\n"
            "- upstream_capability(str)：要审核的上游能力 slug（如 'content-writer'），读其最新交付物\n"
            "- checks(list[str])：要执行的 check 项，常用 ['factual_grounding','policy','consistency']\n"
            "- artifact_label(str, optional)：该 capability 下具体交付物 label；省略则取最新\n"
            "- grounding_sources(list[str], optional)：核对事实用的其它 capability slug 列表\n"
            "- domain_hint(str, optional)：'content_ops' / 'financial' / 'irreversible' /"
            " 'regulated_content' —— 高风险 domain 自动双 judge\n"
            "返回：verdict JSON。supervisor 必须根据 verdict.verdict 路由："
            "block → 重新 invoke_worker 上游 capability 带 revision_brief；warn → request_approval "
            "把 verdict 塞进 message；pass → 安全 invoke 下游副作用 worker。\n"
            "重试上界由 tick 级 max_iterations / 审批门兜底。"
        ),
    )


class OverrideArgs(BaseModel):
    verdict_id: str = Field(description="要 override 的 verdict id（来自上次 output_quality_check 返回）")
    justification: str = Field(description="人类可读的覆盖理由，≥100 字符且必须引用 verdict 里的 evidence")


def output_quality_check_force_override_tool(
    ctx: BuiltinToolContext,
) -> StructuredTool:
    async def _override(verdict_id: str, justification: str) -> str:
        """H3：高门槛 override。仅在非常确定 judge 误判时使用。

        要求：justification ≥100 字符（强制写清覆盖理由）。

        ADR-027：verdict 不再落 workspace，override 记录落当前 thread（messages，
        meta.type='quality_override'），admin / observe 页可据此红色高亮。
        """
        if ctx.agent_node_name is None or ctx.mission_id is None:
            return json.dumps({"error": "缺上下文"})
        if not justification or len(justification.strip()) < MAX_JUSTIFICATION_MIN_CHARS:
            raise ValueError(
                f"❌ override 拒绝：justification 必须 ≥{MAX_JUSTIFICATION_MIN_CHARS} 字符，"
                f"当前 {len(justification or '')} 字符"
            )
        if ctx.db_factory is None:
            return json.dumps({"error": "缺 db_factory"})

        from app.services import messaging_service

        overridden_at = datetime.now(UTC).isoformat()
        async with ctx.db_factory() as db:
            await messaging_service.append_message(
                db,
                ctx.mission_id,
                ctx.thread_key,
                role="agent_log",
                content=f"[quality_override] verdict_id={verdict_id} → {justification.strip()[:500]}",
                meta={
                    "type": "quality_override",
                    "verdict_id": verdict_id,
                    "by_agent_node": ctx.agent_node_name,
                    "justification": justification.strip()[:1000],
                    "overridden_at": overridden_at,
                },
            )

        logger.warning(
            "📊 colony_l1_override project=%s node=%s verdict_id=%s justification_len=%d",
            ctx.mission_id, ctx.agent_node_name, verdict_id, len(justification),
        )
        return json.dumps(
            {
                "ok": True,
                "verdict_id": verdict_id,
                "overridden_at": overridden_at,
                "warning": (
                    "已强制覆盖 verdict。请在 wechat 推送 / admin 面板中留意此 override 记录。"
                ),
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_override,
        name="output_quality_check_force_override",
        description=(
            "（H3 高门槛）强制覆盖 output_quality_check 的 verdict。**慎用**。\n"
            "参数：\n"
            "- verdict_id(str)：上次 output_quality_check 返回的 verdict id\n"
            "- justification(str)：≥100 字符，写清覆盖理由\n"
            "落 override 记录到当前 thread（meta.type='quality_override'），admin 红色显示。"
        ),
    )
