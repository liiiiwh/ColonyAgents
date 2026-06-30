"""媒体处理技能：视频合并 / 转码 / 拼接。

本文件用 ffmpeg 子进程做轻量处理。**生产部署必须保证 PATH 上有 ffmpeg**（项目
Dockerfile 已 COPY backend/bin/ffmpeg → /usr/local/bin/ffmpeg，不依赖 apt）；
macOS / Linux 开发机用 `brew install ffmpeg` 或 `apt install ffmpeg`。

设计原则：
- **只做单一职责**：拼接 N 个视频（concat demuxer），不重编码（如果编码兼容），
  失败时回退重编码（H.264/AAC，浏览器最稳）
- **任意来源**：每个 URL 可以是 nebula / aliyun / 项目 S3 的任意 mp4；先下载
  到临时目录，处理完上传到我们 S3 + 返回 presigned URL
- **不做剪辑 / 转场 / 字幕**：那些场景上层 worker 应当在 prompt 里 inline 给
  video 模型本身（音效 / 旁白都已通过 prompt 由生成模型一次性出）
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shlex
import shutil
import subprocess
import tempfile
import uuid as _uuid
from pathlib import Path

import httpx
from langchain_core.tools import StructuredTool

from app.core.config import settings
from app.services.storage_service import get_storage
from app.skills_builtin.context import BuiltinToolContext

logger = logging.getLogger(__name__)


# ── 配置 ──
_DOWNLOAD_TIMEOUT_SEC = 300.0  # 单个视频下载（典型 5-50 MB） 5 分钟兜底
_FFMPEG_TIMEOUT_SEC = 600.0  # 拼接执行 10 分钟兜底（N=20 段也够用）
_FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"


def _ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


async def _download_video(url: str, dest: Path) -> None:
    """流式下载视频到 dest；空响应 / 4xx / 5xx 都抛错。"""
    async with (
        httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_SEC, follow_redirects=True) as client,
        client.stream("GET", url) as resp,
    ):
        if resp.status_code >= 300:
            raise RuntimeError(f"下载 {url[:80]} 失败 HTTP {resp.status_code}")
        with dest.open("wb") as f:
            async for chunk in resp.aiter_bytes():
                f.write(chunk)
    if dest.stat().st_size == 0:
        raise RuntimeError(f"下载 {url[:80]} 得到空文件")


async def _run_ffmpeg(args: list[str]) -> tuple[int, str]:
    """异步跑 ffmpeg；返回 (returncode, stderr_tail)。stdout 丢弃，stderr 收最后 4KB。"""
    proc = await asyncio.create_subprocess_exec(
        _FFMPEG_BIN, *args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=_FFMPEG_TIMEOUT_SEC)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"ffmpeg 超时（>{_FFMPEG_TIMEOUT_SEC:.0f}s）：{' '.join(shlex.quote(a) for a in args[:6])}…") from None
    stderr_tail = (stderr_bytes or b"").decode("utf-8", errors="replace")[-4096:]
    return proc.returncode or 0, stderr_tail


def merge_videos_tool(ctx: BuiltinToolContext) -> StructuredTool:
    """合并 N 个 mp4 视频成一个；按 URL 顺序串联输出。

    流程：
    1. 全部并发下载到 /tmp/<random>/in_<i>.mp4
    2. ffmpeg concat demuxer（不重编码尝试） → 失败回退 -c:v libx264 -c:a aac 重编码
    3. 上传输出文件到 S3（aux-video/<hash>-<random>.mp4）
    4. 返回 ✅ + 签名 URL
    """

    async def _merge(
        video_urls: list[str],
        output_label: str | None = None,
    ) -> str:
        if not _ffmpeg_available():
            return (
                "⛔ 不可重试：ffmpeg 未在 PATH 上。生产部署应由 Dockerfile COPY "
                "backend/bin/ffmpeg → /usr/local/bin/ffmpeg；本机开发用 "
                "`brew install ffmpeg` 或 `apt install ffmpeg`。"
            )
        if not isinstance(video_urls, list) or not video_urls:
            return "❌ video_urls 必须是非空 list[str]"
        if len(video_urls) > 20:
            return f"❌ 最多支持 20 段视频合并（你传了 {len(video_urls)} 个）"
        if len(video_urls) == 1:
            return f"⚠️ 只有 1 段视频无需合并，直接使用：{video_urls[0]}"

        for i, u in enumerate(video_urls):
            if not isinstance(u, str) or not u.startswith(("http://", "https://")):
                return f"❌ video_urls[{i}] 不是合法 URL：{u!r}"

        # 1. 下载到临时目录
        with tempfile.TemporaryDirectory(prefix="merge_videos_") as tmp:
            tmp_path = Path(tmp)
            input_paths: list[Path] = []
            try:
                await asyncio.gather(*[
                    _download_video(u, tmp_path / f"in_{i:03d}.mp4")
                    for i, u in enumerate(video_urls)
                ])
                for i in range(len(video_urls)):
                    input_paths.append(tmp_path / f"in_{i:03d}.mp4")
            except Exception as exc:
                logger.exception("merge_videos 下载失败")
                return f"❌ 下载片段失败：{exc}"

            # 2. 写 concat 清单 + 第一次尝试 stream copy
            list_file = tmp_path / "list.txt"
            list_file.write_text(
                "\n".join(f"file '{p.as_posix()}'" for p in input_paths) + "\n",
                encoding="utf-8",
            )
            output_path = tmp_path / "out.mp4"
            rc, stderr = await _run_ffmpeg([
                "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", list_file.as_posix(),
                "-c", "copy",
                output_path.as_posix(),
            ])

            # 3. stream copy 失败 → 回退重编码
            if rc != 0 or not output_path.exists() or output_path.stat().st_size == 0:
                logger.info("merge_videos: stream copy 失败，回退重编码。stderr=%s", stderr[:300])
                rc2, stderr2 = await _run_ffmpeg([
                    "-y", "-loglevel", "error",
                    "-f", "concat", "-safe", "0",
                    "-i", list_file.as_posix(),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                    "-c:a", "aac", "-b:a", "192k",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    output_path.as_posix(),
                ])
                if rc2 != 0 or not output_path.exists() or output_path.stat().st_size == 0:
                    return f"❌ ffmpeg 合并失败（重编码后仍失败）：{stderr2[:400]}"

            # 4. 上传到 S3
            blob = output_path.read_bytes()
            sha = hashlib.sha1(blob).hexdigest()[:16]
            key = f"aux-video/{sha}-{_uuid.uuid4().hex[:6]}.mp4"
            try:
                await get_storage().upload(key, blob, content_type="video/mp4")
                signed = await get_storage().presigned_url(
                    key, expires_in=settings.S3_ARTIFACT_URL_EXPIRE,
                )
            except Exception as exc:
                logger.exception("merge_videos 上传 S3 失败")
                return f"⚠️ 合并成功（{len(blob)} bytes）但上传 S3 失败：{exc}"

        label_text = f"（{output_label}）" if output_label else ""
        logger.info(
            "🎬 merge_videos: %d 段 → %s%s（%d bytes）",
            len(video_urls), key, label_text, len(blob),
        )
        return (
            f"✅ 视频合并成功{label_text}：{signed}\n"
            f"  合并了 {len(video_urls)} 段，输出 {len(blob) / 1024 / 1024:.1f} MB。"
        )

    return StructuredTool.from_function(
        coroutine=_merge,
        name="merge_videos",
        description=(
            "把 **N 个 mp4 视频** 按顺序合并成一个 mp4，上传到平台 S3，返回签名 URL。\n"
            "用于视频生成流水线：上游 parallel_invoke_aux_model 输出 N 段 ≤10 秒分镜后，"
            "用本工具串成一个完整视频。\n"
            "参数：\n"
            "- video_urls(list[str], 必填)：mp4 公网 URL 列表（任意来源——nebula / aliyun / volcengine / 项目 S3 都可），"
            "**按列表顺序拼接**\n"
            "- output_label(str, 可选)：用于日志和返回文案标识；不影响输出文件名\n"
            "\n"
            "**特性**：\n"
            "- 优先 stream copy（不重编码，秒级合并、零质量损失）\n"
            "- 编码不一致 / 时间戳冲突时**自动回退**到 libx264 + AAC 重编码（保证 Web 播放兼容）\n"
            "- 上限 20 段；只有 1 段时直接返回原 URL，不浪费 ffmpeg 调用\n"
            "- 输入下载并发拉取，合并耗时 = max(下载时间) + ffmpeg 处理（重编码场景每段约 2-5s）\n"
            "\n"
            "**不做的事**（明确不在 scope）：\n"
            "- 字幕 / 转场 / BGM 混音 —— 这些必须由 video 生成模型在 prompt 阶段一次性出\n"
            "- 任意时间裁剪 / 重排 —— 输入需是想要的最终片段顺序\n"
            "\n"
            "返回 ✅ + 签名 URL。worker 拿到后用 `workspace_write(artifact_type='video')` 落地。"
        ),
    )
