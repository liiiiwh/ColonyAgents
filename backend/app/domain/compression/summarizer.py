"""R3-7 · 压缩摘要纯函数 · 从 compression_service 抽出（进一步瘦最大文件）。

fallback_summarize：LLM 失败时的降级摘要（role + 头尾 content + meta hint）
build_summarize_payload：把待压缩消息序列化成给 summarizer LLM 的 JSON（attachment 缩水防爆）

两者纯（duck-type Message：.role / .content / .meta / .created_at），可独立测。
SUMMARIZE_SYSTEM_PROMPT 也搬过来集中。
"""
from __future__ import annotations

import json
import re
from typing import Any


def fallback_summarize(messages: list[Any]) -> str:
    """降级摘要：LLM 失败时用，保留 role + content 头尾以及简略 meta。"""
    lines: list[str] = []
    for m in messages:
        if not (m.content or m.meta):
            continue
        body = (m.content or "").strip()
        if len(body) > 600:
            body = body[:300] + " … " + body[-300:]
        meta_hint = ""
        meta = m.meta or {}
        if isinstance(meta, dict):
            keys = []
            for k in ("tool_calls", "tool_call", "approval", "form", "artifacts", "artifact"):
                if k in meta and meta[k]:
                    keys.append(k)
            if keys:
                meta_hint = f"  · meta: {','.join(keys)}"
        lines.append(f"- [{m.role}] {body}{meta_hint}")
    return "## 压缩记忆（降级摘要）\n\n" + "\n".join(lines)


def _shrink_attachment(att: dict) -> dict:
    if not isinstance(att, dict):
        return {"_raw": str(att)[:100]}
    t = att.get("type")
    name = att.get("name")
    mt = att.get("media_type")
    content = att.get("content") or ""
    if isinstance(content, str):
        if content.startswith("data:"):
            head = content.split(",", 1)[0]
            size = len(content) - len(head) - 1
            content_repr = f"<data URI {head}, ~{size} bytes base64>"
        elif content.startswith(("http://", "https://", "s3://")):
            content_repr = content[:200]
        elif len(content) > 200:
            content_repr = content[:100] + "…(中略)…" + content[-50:]
        else:
            content_repr = content
    else:
        content_repr = repr(content)[:100]
    out: dict = {"type": t}
    if name:
        out["name"] = name
    if mt:
        out["media_type"] = mt
    out["content_ref"] = content_repr
    return out


def build_summarize_payload(messages: list[Any]) -> str:
    """把待压缩消息序列序列化成给 summarizer LLM 的 JSON 字符串（attachment 缩水）。"""
    items: list[dict] = []
    for m in messages:
        content = m.content or ""
        if len(content) > 2000:
            content = content[:600] + "\n…(中略)…\n" + content[-600:]
        meta = m.meta or {}
        if isinstance(meta, dict) and meta.get("attachments"):
            meta = {**meta, "attachments": [_shrink_attachment(a) for a in meta["attachments"]]}
        items.append({
            "role": m.role,
            "content": content,
            "meta": meta,
            "created_at": (
                m.created_at.isoformat() if getattr(m, "created_at", None) else None
            ),
        })
    return json.dumps(items, ensure_ascii=False, indent=2)


SUMMARIZE_SYSTEM_PROMPT = (
    "你是上下文压缩助手。给定一段对话（含 role / content / meta），输出一段紧凑的中文 "
    "Markdown 摘要。\n\n"
    "**严格输入隔离原则（防 memory 互相污染）**：\n"
    "- 只能根据**我现在给你的这批消息**做摘要——不要引用任何「之前的记忆 / 上一次压缩段」，"
    "因为你完全看不到那些\n"
    "- 不要编造没有出现在本批消息里的对话、工具调用、产物、用户决策\n"
    "- 不要尝试与「未提供」的上下文做连续性推断；遇到指代不清（如「之前说的那个」「上次的方案」）"
    "原样保留措辞，不要替它补全\n"
    "- 摘要本身是**自包含**段落，未来会被原样拼接到 memory 末尾——所以避免使用「继上一段」之类的衔接词\n\n"
    "**必须保留**：\n"
    "1. 时间线大纲（按 turn）\n"
    "2. 用户关键决策与确认点\n"
    "3. tool_call 序列（工具名 + 关键入参 + 是否成功）\n"
    "4. 出现过的 approval / form 卡片（标题 + 用户选择）\n"
    "5. 产生过的 artifact（label + s3_url + type）\n"
    "6. **用户上传过的附件**（来自 meta.attachments）：列出 type / name / media_type / "
    "content_ref（URL 或 data URI 摘要）；如有图片，明确标注「用户在 T 上传图片 foo.png」"
    "—— 你看不到图像本身，但要把它的存在记录下来，便于后续 Supervisor 必要时引用或重传\n"
    "丢掉：寒暄、重复、token 流式 delta。\n\n"
    "输出严格按以下 section 排版：\n"
    "## 概要(<= 100 字)\n"
    "## 时间线\n"
    "## 决策\n"
    "## 工具调用\n"
    "## 卡片\n"
    "## 产物\n"
    "## 用户附件"
)
