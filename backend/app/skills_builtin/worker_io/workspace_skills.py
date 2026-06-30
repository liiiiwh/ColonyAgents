"""Workspace 工具族：写交付物（ADR-027 D3，按 capability 归档）。

`workspace_write` 会（仅交付物 Agent）：
1. 通过 `ctx.db_factory` 获取独立 DB Session
2. 把产物上传 S3（key = colony/workspace/{mission_id}/{capability}/{label}-{id}.<ext>）
3. 通过 `ctx.event_queue` 向 chat SSE 流推送 `data-artifact` 事件，前端实时渲染

ADR-027：退役 by-node workspace 簿记（mission.workspace[node_name]）。交付物只活在 S3 +
data-artifact 事件；非交付物的中间态留在 worker thread。
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from langchain_core.tools import StructuredTool

from app.schemas.message import Artifact
from app.services import mission_service, workspace_service
from app.services.storage_service import get_storage
from app.services.workspace_service import _slugify_segment
from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


ArtifactType = Literal["markdown", "text", "json", "image", "html", "file", "3d-model", "video"]


async def _resolve_capability(ctx: BuiltinToolContext) -> str:
    """解析当前 worker 的 capability（用于 S3 归档段）。

    优先用 ctx.agent_id 查 Agent.capability；查不到则回退到 agent_node_name / 'default'。
    """
    agent_id = getattr(ctx, "agent_id", None) or (ctx.extra or {}).get("agent_id")
    if agent_id and ctx.db_factory is not None:
        try:
            from app.services import agent_service

            async with ctx.db_factory() as db:
                worker = await agent_service.get_agent(db, agent_id)
                if worker and getattr(worker, "capability", None):
                    return str(worker.capability)
        except Exception:
            logger.warning("[workspace_write] 解析 capability 失败（回退 default）", exc_info=True)
    return (ctx.agent_node_name or "default")


def workspace_write_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _write(
        label: str,
        content: str,
        artifact_type: ArtifactType = "markdown",
    ) -> str:
        """写入产物（ADR-027 D3，按当前 worker 的 capability 归档）。

        行为由当前 Agent 的 `produces_deliverable` 开关决定：
        - True（交付物 Agent）→ 上传 S3（key 按 capability + label），推送 data-artifact
        - False（中间态 Agent）→ 不上传 S3、不推送 data-artifact；内容留在 worker thread 即可
        """
        if ctx.mission_id is None or ctx.db_factory is None:
            return "❌ 工具上下文缺失（mission_id / db_factory），无法写入"
        # Supervisor 不产交付物，不应 workspace_write（应通过 invoke_worker 让 worker 写）
        if ctx.agent_node_name == "supervisor":
            return (
                "❌ Supervisor 不允许 workspace_write；请用 invoke_worker(capability:slug, ...) "
                "把要保存的数据交给对应 Worker 写入，或通过 message/memory 通道传递。"
            )
        media_map = {
            "markdown": "text/markdown",
            "text": "text/plain",
            "json": "application/json",
            "html": "text/html",
            "image": "image/png",  # 图片默认 png；真实 MIME 由生成方决定
            "file": "application/octet-stream",
            "3d-model": "model/gltf-binary",
            "video": "video/mp4",
        }
        # **类型自动纠正**：Agent prompt 难以保证每次都设对 artifact_type；
        # 若 content 是纯 JSON 且不含 markdown 标记，自动改成 json。
        # E13：加启发式 —— 含 markdown 标记（# / | / ``` / **）时**不**纠正，避免误伤
        if artifact_type in ("markdown", "text", "file"):
            try:
                import json as _json
                import re as _re
                stripped = (content or "").strip()
                # 含明显 markdown 结构标记 → 不纠正
                has_md_marker = bool(_re.search(
                    r"(^|\n)\s*#{1,6}\s|"          # heading
                    r"^\s*\|.*\|.*\n\s*\|[\s:-]+\||"  # table（带分隔行）
                    r"```|"                          # 代码块围栏
                    r"\*\*\w",                       # 加粗
                    stripped,
                ))
                if (
                    stripped
                    and stripped[0] in "{["
                    and len(stripped) <= 1_000_000
                    and not has_md_marker
                ):
                    _json.loads(stripped)
                    logger.info(
                        "[workspace_write] 类型自动修正：%s → json（label=%r 内容是合法 JSON 且无 markdown 标记）",
                        artifact_type, label,
                    )
                    artifact_type = "json"
            except (ValueError, TypeError):
                pass
        # E14：仅当 artifact_type=image 且 URL 看起来是图片（后缀含 .png/.jpg/... 或
        # path 含 /image/ 等强信号）才作为 s3_url 提取；防止把文档链接误当图片
        extracted_s3_key: str | None = None
        extracted_s3_url: str | None = None
        if artifact_type == "image":
            import re as _re

            m = _re.search(r"https?://[^\s'\"<>]+", content or "")
            if m:
                url = m.group(0)
                # E14 启发式：扩展名 / 关键路径强信号
                is_image_url = bool(
                    _re.search(r"\.(png|jpe?g|gif|webp|svg|bmp|tiff?|heic|avif)(\?|$|#|/)",
                               url, _re.IGNORECASE)
                    or "/image" in url.lower()
                    or "imagedelivery" in url.lower()
                )
                if is_image_url:
                    extracted_s3_url = url
                    if ctx.produces_deliverable:
                        content = ""
                else:
                    logger.info(
                        "[workspace_write] image content 含 URL 但不像图片资源，"
                        "保留 content 不当 s3_url 提取：url=%s",
                        url[:200],
                    )
        # HTML artifact 占位符替换（ADR-020 mission-only）：
        # agent 在 prompt 里写 `const MID = "__SESSION_ID__"` 等占位符，后端落库时替换成真实
        # mission_id / thread_key（agent 拿不到 ctx 内部状态）。__SESSION_ID__/__BRANCH_ID__
        # 为历史占位符名，分别映射 mission_id（mission_id）/ thread_key。
        if artifact_type == "html" and content:
            if ctx.mission_id and "__SESSION_ID__" in content:
                content = content.replace("__SESSION_ID__", str(ctx.mission_id))
            if ctx.thread_key and "__BRANCH_ID__" in content:
                content = content.replace("__BRANCH_ID__", str(ctx.thread_key))
        artifact = Artifact(
            type=artifact_type,
            label=label,
            content=content,
            media_type=media_map[artifact_type],
            s3_key=extracted_s3_key,
            s3_url=extracted_s3_url,
        )
        capability = await _resolve_capability(ctx)
        db_factory = ctx.db_factory
        async with db_factory() as db:
            mission = await mission_service.get_mission(db, ctx.mission_id)
            if not mission:
                return f"❌ Mission {ctx.mission_id} 不存在"
            artifact = await workspace_service.write_artifact(
                db,
                mission,
                artifact,
                capability=capability,
                is_deliverable=ctx.produces_deliverable,
            )
        # 仅交付物推送 data-artifact（前端内联 ArtifactPreview + DeliverablesProgress 依赖此事件）
        if ctx.produces_deliverable:
            await ctx.emit(
                {
                    "type": "data-artifact",
                    "data": {
                        "capability": capability,
                        "artifact": artifact.model_dump(mode="json"),
                    },
                }
            )
        logger.info(
            "🧱 workspace_write: thread=%s capability=%s label=%s type=%s size=%d deliverable=%s",
            ctx.thread_key,
            capability,
            label,
            artifact_type,
            len(content),
            ctx.produces_deliverable,
        )
        if ctx.produces_deliverable:
            return (
                f"✅ 已写入交付物 [{capability}] {label}（{artifact_type}，{len(content)} 字符，已上传 S3）"
            )
        return (
            f"✅ 已记录中间态 {label}（{artifact_type}，{len(content)} 字符，未上传 S3；"
            "内容留在对话上下文供后续步骤消费）"
        )

    return StructuredTool.from_function(
        coroutine=_write,
        name="workspace_write",
        description=(
            "写入你这次产出的内容（按你的 capability 自动归档，无需指定节点）。\n"
            "参数：label(str，标题) / content(str) / "
            "artifact_type(markdown|text|json|image|html|file，默认 markdown)。\n"
            "**artifact_type 选择规则（务必正确填写，前端按它选渲染器）**：\n"
            "• content 是 Markdown 文本（# 标题 / 表格 / 列表 / 代码块）→ `markdown`\n"
            "• content 是纯 JSON 对象/数组（如 `{...}` `[{...}]`）→ **`json`**（**不要**写 markdown）\n"
            "• content 是纯文本无格式 → `text`\n"
            "• content 是 HTML 片段（含 <tag>）→ `html`\n"
            "• content 是图片 URL → `image`\n"
            "（如果你不小心声明错了，后端会在 content 是合法 JSON 时**自动改成 json**，但请在 prompt 阶段就写对。）\n"
            "⚠️ 行为由当前 Agent 的 `produces_deliverable` 属性决定：\n"
            "• 交付物 Agent → 上传 S3 + 在对话中内联展示（用户可预览 + 下载）\n"
            "• 过程态 Agent → 不上 S3、不内联展示；内容留在对话上下文供后续步骤消费"
        ),
    )


_TEXT_EXTS = frozenset({"md", "txt", "json", "html"})


def workspace_read_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _read(capability: str, label: str | None = None) -> str:
        """读取某 capability 的交付物（ADR-027：交付物只活在 S3，按 capability 归档）。

        从 `colony/workspace/{mission_id}/{capability_slug}/` 列对象；
        - 指定 label → 匹配 key 含该 label slug 的对象；
        - 否则取最新对象（按 last_modified）。
        文本类（md/txt/json/html）下载并 utf-8 解码返回；二进制/图片返回 presigned_url 行。
        """
        if ctx.mission_id is None:
            return "❌ 工具上下文缺失（mission_id）"
        cap_slug = _slugify_segment(capability)
        prefix = f"colony/workspace/{ctx.mission_id}/{cap_slug}/"
        storage = get_storage()
        objects = [o for o in await storage.list_objects(prefix) if o.get("key")]
        if not objects:
            return f"⚠️ capability [{capability}] 暂无交付物"

        # label 过滤：匹配 key 文件名里含该 label slug 的对象
        if label:
            lbl_slug = _slugify_segment(label)
            matched = [o for o in objects if lbl_slug in o["key"].rsplit("/", 1)[-1]]
            if not matched:
                return f"⚠️ capability [{capability}] 下未找到 label≈{label} 的交付物"
            objects = matched

        # 按 last_modified 排序取最新（list_objects 已带 last_modified）
        objects.sort(key=lambda o: o.get("last_modified") or "")
        latest = objects[-1]
        key = latest["key"]
        ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""

        # 概览：列出该 capability 下所有交付物
        lines = [f"- {o['key'].rsplit('/', 1)[-1]}" for o in objects]
        summary = "\n".join(lines)

        if ext in _TEXT_EXTS:
            try:
                body = await storage.download(key)
                text = body.decode("utf-8")
            except Exception:
                logger.warning("[workspace_read] 下载/解码失败 key=%s", key, exc_info=True)
                text = f"（下载失败，可通过 s3_download 读取 key={key}）"
            return (
                f"# capability [{capability}]（{len(objects)} 个交付物）\n\n"
                f"{summary}\n\n### 最新产物：{key.rsplit('/', 1)[-1]}\n\n{text}"
            )
        # 二进制 / 图片 → presigned_url
        try:
            url = await storage.presigned_url(key)
            body_line = f"[{ext or 'file'}] {key.rsplit('/', 1)[-1]}: {url}"
        except Exception:
            body_line = f"[{ext or 'file'}] s3_key={key}（需通过 s3_download 读取）"
        return (
            f"# capability [{capability}]（{len(objects)} 个交付物）\n\n"
            f"{summary}\n\n### 最新产物：\n\n{body_line}"
        )

    return StructuredTool.from_function(
        coroutine=_read,
        name="workspace_read",
        description=(
            "按 capability 读取交付物（ADR-027：交付物存 S3，按 capability 归档，不再按节点）。"
            "参数：capability(str，要读的能力 slug，如 'content-writer') / "
            "label(str 可选；指定则匹配该 label 的交付物，省略则返回该 capability 下产物概览 + 最新产物全文)。"
        ),
    )


def workspace_write_batch_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _write_batch(items: list[dict]) -> str:
        """一次性把多个交付物上传 S3（ADR-027 D3，按 capability 归档）。

        items 每项 dict 形如 {"label": str, "content": str, "artifact_type": "image"|"markdown"|...}
        - artifact_type=image 且 content 是 URL 时，自动按 URL 写 s3_url，不重复上传
        - 其他类型按 content + media_map 推 MIME 后上传 S3
        """
        if ctx.mission_id is None or ctx.db_factory is None:
            return "❌ 工具上下文缺失"
        if ctx.agent_node_name == "supervisor":
            return "❌ Supervisor 不允许 workspace_write_batch"
        if not items or not isinstance(items, list):
            return "❌ items 必须是非空列表"
        if not ctx.produces_deliverable:
            return (
                "⚠️ 当前 Agent 不是交付物 Agent (produces_deliverable=False)，"
                "workspace_write_batch 仅对交付物 Agent 有意义。"
                "请单条 workspace_write 走 state 路径。"
            )

        media_map = {
            "markdown": "text/markdown",
            "text": "text/plain",
            "json": "application/json",
            "html": "text/html",
            "image": "image/png",
            "file": "application/octet-stream",
            "3d-model": "model/gltf-binary",
            "video": "video/mp4",
        }
        from app.schemas.message import Artifact

        prepared: list[Artifact] = []
        import re as _re

        for it in items:
            if not isinstance(it, dict):
                continue
            label = str(it.get("label") or "").strip()
            atype = str(it.get("artifact_type") or "markdown")
            content = it.get("content") or ""
            if not label or atype not in media_map:
                logger.warning("workspace_write_batch 跳过非法项: %r", it)
                continue
            extracted_s3_url: str | None = None
            if atype == "image":
                m = _re.search(r"https?://[^\s'\"<>]+", content or "")
                if m:
                    extracted_s3_url = m.group(0)
                    content = ""  # 防止当 image bytes 上传
            prepared.append(Artifact(
                type=atype,  # type: ignore[arg-type]
                label=label,
                content=content,
                media_type=media_map[atype],
                s3_url=extracted_s3_url,
            ))
        if not prepared:
            return "❌ items 全部不合法"

        capability = await _resolve_capability(ctx)
        async with ctx.db_factory() as db:
            mission = await mission_service.get_mission(db, ctx.mission_id)
            if not mission:
                return "❌ Mission 不存在"
            saved = await workspace_service.write_artifacts_batch(
                db, mission, prepared, capability=capability,
            )

        # 推批量事件让前端一次性刷新 artifacts 列表
        await ctx.emit({
            "type": "data-artifacts-batch",
            "data": {
                "capability": capability,
                "artifacts": [a.model_dump(mode="json") for a in saved],
            },
        })
        return (
            f"✅ 已批量写入 {len(saved)} 条交付物 [{capability}]：\n"
            + "\n".join(f"  - [{a.type}] {a.label}: {a.s3_url or a.s3_key}" for a in saved)
        )

    return StructuredTool.from_function(
        coroutine=_write_batch,
        name="workspace_write_batch",
        description=(
            "一次性把**多个**交付物上传 S3（按你的 capability 归档）。"
            "适合一个 worker 要交付多个文件（如三视图 / 多附件）的场景。\n"
            "参数：\n"
            "- items: list[{label: str, content: str, artifact_type: 'markdown'|'text'|'json'|'image'|'html'|'file'|'3d-model'|'video'}]\n"
            "  artifact_type=image 时 content 可以直接是 URL 字符串（自动作为 s3_url 落到 artifact）。"
        ),
    )


def workspace_list_tool(ctx: BuiltinToolContext) -> StructuredTool:
    async def _list() -> str:
        """列出当前 Mission 所有交付物（ADR-027：按 capability 分组，源自 S3）。"""
        if ctx.mission_id is None:
            return "❌ 工具上下文缺失"
        prefix = f"colony/workspace/{ctx.mission_id}/"
        storage = get_storage()
        objects = [o for o in await storage.list_objects(prefix) if o.get("key")]
        if not objects:
            return "⚠️ 当前 Mission 暂无任何产物"
        # 按 prefix 后的第一段（capability）分组
        groups: dict[str, list[str]] = {}
        for o in objects:
            rest = o["key"][len(prefix):]
            parts = rest.split("/", 1)
            if len(parts) < 2:
                continue  # 跳过非 capability/label 结构的对象
            cap = parts[0]
            label = parts[1].rsplit("/", 1)[-1]
            groups.setdefault(cap, []).append(label)
        if not groups:
            return "⚠️ 当前 Mission 暂无任何产物"
        lines = []
        for cap, labels in sorted(groups.items()):
            lines.append(f"- {cap}: {len(labels)} 个产物 [{', '.join(labels)}]")
        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_list,
        name="workspace_list",
        description="列出当前 Mission 所有交付物（按 capability 分组，含每个 capability 的产物数 + label）。无参数。",
    )


def _format_artifact(a: dict) -> str:
    """把 Artifact dict 转为 Markdown 文本（供 Agent 消费）。

    **原则：不截断**。交付物是最终产物，下游 Agent / 用户审阅都需要完整内容；
    截断过会导致 Agent 读回来自己刚写的文档只见 4000 字符 → 以为上次写短了
    → 重新写一版 → 再次被截 → 级联信息丢失。
    若担心 token 超限，应在 Agent prompt / summarizer 层收敛，而不是在工具层偷偷砍。

    输出优先级：
    1. content 非空 → 直接返回（markdown / json / 文本类）
    2. s3_url 存在 → 「[type] label: <s3_url>」（image / 3d-model / video / 通过 invoke_aux_model
       直传 URL 写入的 image 等场景，content 为空但 s3_url 是直接可用 URL）
    3. s3_key 存在 → 「[type] s3_key=... (需 s3_download)」（生产路径，需要后端解码）
    4. 兜底：返回 type+label 元数据，避免完全空字符串误导下游 LLM
    """
    content = a.get("content") or ""
    if content:
        return content
    s3_url = a.get("s3_url") or ""
    if s3_url:
        return f"[{a['type']}] {a.get('label', '')}: {s3_url}"
    s3_key = a.get("s3_key") or ""
    if s3_key:
        return f"[{a['type']}] s3_key={s3_key} (需通过 s3_download 读取)"
    return f"[{a['type']}] {a.get('label', '(无内容)')}"


def _uuid_or_none(val: object) -> uuid.UUID | None:
    if not val:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return None
