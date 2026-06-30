"""ADR-008 P5 · Builder spec 校验（纯函数，可独立测）。

工厂层 fail-fast 用：
- validate_capability_contract：advertises 每项必有 action + side_effects(list) + requires_approval(bool)
- missing_skills：请求的 skill 哪些不存在（工厂据此报错，不静默跳过）
- check_backward_compat：升级现有 worker 时比对新旧 contract（旧 action 不许删/不许加 required input/不许删 output）

check_backward_compat 是从 builder_v3_skills.validate_backward_compat_tool 抽出的纯核，
工厂强制调用 + 那个 tool 也复用它。
"""
from __future__ import annotations

from collections.abc import Iterable


class MissingSkillsError(ValueError):
    """ADR-009 G6 · 工厂硬门遇到 skill 缺失时抛出（携带 missing 列表，供 Builder 优雅降级）。

    Builder build_* 工具捕获它 → 返回结构化 {missing_skills, hint}，让 Builder 选择
    create_skill_from_template / install_skill / 向人求助，而非死循环。
    """

    def __init__(self, missing: list[str], *, agent_kind: str, slug: str) -> None:
        self.missing = missing
        self.agent_kind = agent_kind
        self.slug = slug
        super().__init__(
            f"{agent_kind}「{slug}」请求的 skill 未安装: {missing}。"
            "可 create_skill_from_template（白名单模板）/ install_skill（ClawHub）/ 向用户求助后再建。"
        )


def validate_capability_contract(contract: dict) -> list[str]:
    """校 capability_contract 结构。返回 violations 列表（空=合法）。"""
    violations: list[str] = []
    if not isinstance(contract, dict):
        return ["capability_contract 必须是对象(dict)"]
    advertises = contract.get("advertises")
    if not isinstance(advertises, list) or not advertises:
        violations.append("capability_contract.advertises 必须是非空数组")
        return violations
    for i, a in enumerate(advertises):
        if not isinstance(a, dict):
            violations.append(f"advertises[{i}] 必须是对象")
            continue
        action = a.get("action")
        if not isinstance(action, str) or not action.strip():
            violations.append(f"advertises[{i}].action 必填且非空")
        if "side_effects" not in a:
            violations.append(f"advertises[{i}].side_effects 必填（副作用标签数组，如 ['external_write']）")
        elif not isinstance(a.get("side_effects"), list):
            violations.append(f"advertises[{i}].side_effects 必须是数组")
        if "requires_approval" not in a:
            violations.append(f"advertises[{i}].requires_approval 必填（平台审批门，bool）")
        elif not isinstance(a.get("requires_approval"), bool):
            violations.append(f"advertises[{i}].requires_approval 必须是 bool")
    return violations


def missing_skills(requested: Iterable[str], found_slugs: Iterable[str]) -> list[str]:
    """请求的 skill 里哪些不存在于已安装 skill（found_slugs）。"""
    return sorted(set(requested) - set(found_slugs))


def _required_fields(schema: dict) -> set[str]:
    """简易 schema：dict[field] = 'str' / 'str?'；? 后缀表示 optional。"""
    return {k for k, v in (schema or {}).items() if isinstance(v, str) and not v.endswith("?")}


def _action_break_reasons(old_spec: dict | None, new_spec: dict | None) -> list[str]:
    """某个 action 从 old_spec → new_spec 是否破坏调用方。返回原因列表（空=兼容）。"""
    reasons: list[str] = []
    if new_spec is None:
        reasons.append("action 被删除")
        return reasons
    old_req = _required_fields(old_spec.get("input_schema") or {}) if old_spec else set()
    new_req = _required_fields(new_spec.get("input_schema") or {})
    added_required = new_req - old_req
    if added_required:
        reasons.append(f"新增 required input 字段 {sorted(added_required)}")
    old_out = set((old_spec.get("output_schema") or {}).keys()) if old_spec else set()
    new_out = set((new_spec.get("output_schema") or {}).keys())
    removed_out = old_out - new_out
    if removed_out:
        reasons.append(f"删除 output 字段 {sorted(removed_out)}")
    return reasons


def analyze_worker_change_impact(
    *, old_contract: dict, new_contract: dict, consumers: list[dict]
) -> dict:
    """ADR-009 G1 · 改 worker 前的跨 super 影响分析（纯）。

    consumers: [{"super_slug": str, "used_actions": list[str]}] —— 每个消费 super
    实际用过的 action 集（声明 ∪ 观测）。

    对每个 consumer 的每个 used_action，比对新旧契约：只要破坏就记进 breaking。
    比 check_backward_compat 严：action 即便进了 deprecated_actions，只要仍被某 super 使用，
    删除就算破坏（不能「一边好一边坏」）。

    返回 {safe, breaking:[{super_slug, broken_actions, reasons}], warnings}
    """
    old_acts = {a.get("action"): a for a in (old_contract.get("advertises") or []) if isinstance(a, dict)}
    new_acts = {a.get("action"): a for a in (new_contract.get("advertises") or []) if isinstance(a, dict)}
    breaking: list[dict] = []
    warnings: list[str] = []
    for consumer in consumers:
        slug = consumer.get("super_slug") or consumer.get("super_agent_id") or "?"
        used = consumer.get("used_actions") or []
        broken_actions: list[str] = []
        reasons: list[str] = []
        for action_name in used:
            if action_name not in old_acts:
                # 该 super 用了一个旧契约里就没有的 action（脏数据/越权调用）→ 不在本次升级判定范围
                warnings.append(f"super {slug!r} 用过未在旧契约声明的 action {action_name!r}（忽略）")
                continue
            r = _action_break_reasons(old_acts.get(action_name), new_acts.get(action_name))
            if r:
                broken_actions.append(action_name)
                reasons.extend(f"{action_name}: {x}" for x in r)
        if broken_actions:
            breaking.append({
                "super_slug": slug,
                "broken_actions": broken_actions,
                "reasons": reasons,
            })
    return {"safe": len(breaking) == 0, "breaking": breaking, "warnings": warnings}


def check_backward_compat(old_contract: dict, new_contract: dict) -> dict:
    """比对新旧 capability_contract 向下兼容性（纯）。

    规则：旧 action 必须保留（或进 deprecated_actions）；旧 action 不许新增 required input；
    旧 action 不许删除 output 字段。返回 {compatible, violations, warnings, old_actions, new_actions}。
    """
    old_acts = {a.get("action"): a for a in (old_contract.get("advertises") or []) if isinstance(a, dict)}
    new_acts = {a.get("action"): a for a in (new_contract.get("advertises") or []) if isinstance(a, dict)}
    deprecated = new_contract.get("deprecated_actions") or []
    violations: list[str] = []
    warnings: list[str] = []
    for action_name, old_spec in old_acts.items():
        new_spec = new_acts.get(action_name)
        if new_spec is None:
            if action_name in deprecated:
                warnings.append(f"action {action_name!r} 已 deprecated（兼容；但所有 super 应避免新调用）")
            else:
                violations.append(f"action {action_name!r} 缺失（既未保留也未 deprecate）❌ 破坏向下兼容")
            continue
        old_req = _required_fields(old_spec.get("input_schema") or {})
        new_req = _required_fields(new_spec.get("input_schema") or {})
        new_required_added = new_req - old_req
        if new_required_added:
            violations.append(
                f"action {action_name!r} 新增 required input 字段 {sorted(new_required_added)} ❌（只能 optional）"
            )
        old_out = set((old_spec.get("output_schema") or {}).keys())
        new_out = set((new_spec.get("output_schema") or {}).keys())
        removed = old_out - new_out
        if removed:
            violations.append(f"action {action_name!r} 删除 output 字段 {sorted(removed)} ❌")
    return {
        "compatible": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "old_actions": list(old_acts.keys()),
        "new_actions": list(new_acts.keys()),
    }
