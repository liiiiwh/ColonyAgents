"""R3-5 · 微信审批回信意图解析纯核心（风控关键路径）。

从 wechat_intent.py 抽出 parse_json_loose + fallback_classify：free text → 决策 dict。
纯函数（pending 只 duck-type .request_id / .options / .title），不碰 LLM / DB → 边界可单测。

匹配优先级（fallback_classify，LLM 失败/不可用时兜底）：
1. 文本含 request_id 8-hex 短码 → 锁定该 pending 试匹配 option
2. 全表精确选项匹配（含 emoji 前缀）→ 唯一命中即 decide，多命中 unclear
3. 单 pending + 正/负向关键词 → 选对应 option
4. 都不中 → unclear（绝不瞎批）
"""
from __future__ import annotations

import json
import re
from typing import Any


def parse_json_loose(text: str) -> Any:
    """从 LLM 输出里抽第一个 {...} JSON。"""
    s = (text or "").strip()
    if s.startswith("```"):
        first_brace = s.find("{")
        last_brace = s.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            s = s[first_brace : last_brace + 1]
    elif "{" in s:
        first_brace = s.find("{")
        last_brace = s.rfind("}")
        s = s[first_brace : last_brace + 1]
    return json.loads(s)


def _pick_for_pending(p: Any, text: str, lower: str) -> str | None:
    """用户文本里能否找到 p.options 中某个精确选项？"""
    opts = list(getattr(p, "options", None) or [])
    for opt in opts:
        if opt and opt in text:
            return opt
    for opt in opts:
        core = re.sub(r"[^一-鿿 a-zA-Z]+", "", opt or "").strip()
        if core and core in text:
            return opt
    # 用户输入是某选项的「头部标签」（如「确认」对「确认，按此配置创建」）→ 命中
    if len(text) >= 2:
        for opt in opts:
            head = re.split(r"[，,、:：/\s]", (opt or "").strip(), 1)[0].strip()
            if head and (head == text or (opt or "").startswith(text)):
                return opt
    pos = any(w in lower for w in ("ok", "好", "行", "可以", "yes", "确认", "确定", "是的")) or \
          any(w in text for w in ("通过", "同意", "发布", "✓", "✅"))
    neg = any(w in lower for w in ("no", "不行", "不要", "取消")) or \
          any(w in text for w in ("驳回", "拒", "✗", "❌"))
    if pos and not neg:
        for opt in opts:
            if any(c in opt for c in ("通", "同", "发", "✓", "✅")):
                return opt
        return opts[0] if opts else None
    if neg and not pos:
        for opt in opts:
            if any(c in opt for c in ("驳", "拒", "✗", "❌", "不")):
                return opt
        return opts[-1] if opts else None
    return None


def fallback_classify(user_text: str, pendings: list[Any], err: str) -> dict[str, Any]:
    """LLM 失败时的兜底意图判定。"""
    text = (user_text or "").strip()
    lower = text.lower()

    # 1) 显式 request_id 短码
    m = re.search(r"\b([a-f0-9]{8})\b", lower)
    target = None
    if m:
        cand = m.group(1)
        target = next((p for p in pendings if p.request_id == cand), None)

    if target is not None:
        opt = _pick_for_pending(target, text, lower)
        if opt:
            return {
                "intent": "decide_approval",
                "request_id": target.request_id,
                "option": opt,
                "reply_text": f"✅ 已记录决策：{opt}（针对 [{target.request_id}]）。",
            }
        return {
            "intent": "unclear",
            "reply_text": (
                f"[{target.request_id}] 候选选项：{target.options}。请回复其中一个精确文本。"
            ),
        }

    # 2) 全表精确选项匹配
    direct_hits: list[tuple[Any, str]] = []
    for p in pendings:
        opt = _pick_for_pending(p, text, lower)
        if opt:
            direct_hits.append((p, opt))
    if len(direct_hits) == 1:
        only_p, opt = direct_hits[0]
        return {
            "intent": "decide_approval",
            "request_id": only_p.request_id,
            "option": opt,
            "reply_text": f"✅ 已记录决策：{opt}（针对 [{only_p.request_id}]）。",
        }
    if len(direct_hits) > 1:
        lines = [
            f"- [{p.request_id}] {getattr(p, 'title', '')}（候选选项：{p.options}）"
            for p, _ in direct_hits[:5]
        ]
        return {
            "intent": "unclear",
            "reply_text": (
                "多条待审批都包含你说的关键词，请带上 request_id 再发一次：\n"
                + "\n".join(lines)
                + "\n格式示例：`abc12345 通过`"
            ),
        }

    # 3) 单条 pending → 关键词宽松匹配
    if len(pendings) == 1:
        only = pendings[0]
        opt = _pick_for_pending(only, text, lower)
        if opt:
            return {
                "intent": "decide_approval",
                "request_id": only.request_id,
                "option": opt,
                "reply_text": f"✅ 已记录决策：{opt}（针对 [{only.request_id}]）。",
            }

    # err（LLM JSON 解析错误等）是内部诊断，不透给用户。
    if len(pendings) == 1:
        only = pendings[0]
        return {
            "intent": "unclear",
            "reply_text": (
                f"没太理解你的回复。当前待审「{getattr(only, 'title', '') or only.request_id}」，"
                f"请直接回复其中一个选项：{' / '.join(only.options or [])}"
            ),
        }
    return {
        "intent": "unclear",
        "reply_text": (
            f"未识别到匹配的待审批。当前待审 {len(pendings)} 条，"
            f"请带 request_id（前 8 位 hex）+ 选项再发一次，例如：`abc12345 通过`。"
        ),
    }
