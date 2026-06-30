"""M6: 远程 Skill 安装器。

职责：从 ClawHub 下载 + 解压 + 判 runtime kind + 写 DB + 镜像本地 Skill。

设计：
- install(): 下载 ZIP → 解压到 `{CLAWHUB_INSTALL_DIR}/{slug}@{version}/` →
  检测 runtime_kind（python / node / nextjs / mcp-server / static-instruction）
  → 不在本步骤运行依赖安装（避免长阻塞 + 引入安全风险）；entrypoint/wrapper 路径写入 DB
  → 在 `skills` 表创建/更新 mirror 行（is_builtin=False，category='installer'，
    builtin_ref=远程 install id），Agent 可绑这条 mirror
- inspect(): 调 clawhub_client.get_skill + security_summary + 拎 highrisk tags（不下载）
- uninstall(): 删 DB 行 + 删本地解压目录 + 删 mirror skill 行

Skill 调用：M6 阶段 mirror skill 的 builtin_ref='remote_skill_invoke'，注册一个
通用 stub 工具来读 RemoteSkillInstall 行 → 直接调 entrypoint（仅 python kind 支持执行；
其余 kind 返回 "M7+ 尚未接入"）。这样让 Agent 至少能 bind，UI 全打通；后续按 kind 逐个接。
"""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
import uuid
import zipfile
from collections.abc import Sequence
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.skill import RemoteSkillInstall, Skill
from app.services import clawhub_client

logger = logging.getLogger(__name__)


SAFE_SLUG_RE = re.compile(r"^[a-zA-Z0-9._@/-]+$")


def _safe_name(s: str) -> str:
    """用于安装目录名 —— 保留点号便于人类识别版本（如 `fetch@1.0.0`）。"""
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s)


def _safe_slug(s: str) -> str:
    """用于 skills 表的 slug 字段 —— 必须匹配 `^[a-z0-9][a-z0-9_-]*$`（**不含点**）。

    将 `clawhub-fetch-1.0.0` 转成 `clawhub-fetch-1_0_0`，让 API 层 Pydantic
    校验通过、Builder agent 能继续 list / bind 这些镜像 skill。
    """
    s = s.lower()
    # 1) 非 [a-z0-9_-] 一律替换为 `_`（含点号、空格、其他符号）
    s = re.sub(r"[^a-z0-9_-]+", "_", s)
    # 2) 首字符必须是 [a-z0-9]：若以 `_-` 开头，前面加 `s`
    if s and not s[0].isalnum():
        s = "s" + s
    return s or "skill"


def install_root() -> Path:
    root = Path(settings.CLAWHUB_INSTALL_DIR)
    if not root.is_absolute():
        # 相对路径基于 backend/ 父目录（项目根）
        root = Path(__file__).resolve().parents[3] / settings.CLAWHUB_INSTALL_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def install_dir_for(slug: str, version: str) -> Path:
    return install_root() / f"{_safe_name(slug)}@{_safe_name(version)}"


# ─────────────────────────── runtime kind 检测 ───────────────────────────
def detect_runtime_kind(install_dir: Path) -> tuple[str, str | None]:
    """根据目录里的 manifest 文件判断 runtime_kind + entrypoint。

    返回 (kind, entrypoint)；entrypoint 可能是 file path / module name / null。
    优先级：openclaw.plugin.json > pyproject/requirements > package.json > 其他。
    """
    plugin_manifest = install_dir / "openclaw.plugin.json"
    if plugin_manifest.exists():
        try:
            spec = json.loads(plugin_manifest.read_text(encoding="utf-8"))
            # 看 plugin metadata
            host = (spec.get("openclaw") or {}).get("hostTargets") or []
            if isinstance(host, list) and "mcp" in [str(h).lower() for h in host]:
                return "mcp-server", spec.get("main") or spec.get("entry")
            if (install_dir / "package.json").exists():
                return "node", spec.get("main") or "index.js"
            return "static-instruction", None
        except Exception:
            logger.exception("[installer] openclaw.plugin.json 解析失败 %s", install_dir)

    if (install_dir / "pyproject.toml").exists() or (install_dir / "requirements.txt").exists():
        # 进一步找 entry：__main__.py / main.py / skill.py
        for cand in ("__main__.py", "main.py", "skill.py"):
            if (install_dir / cand).exists():
                return "python", cand
        return "python", None

    pkg = install_dir / "package.json"
    if pkg.exists():
        try:
            j = json.loads(pkg.read_text(encoding="utf-8"))
            # Next.js 关键标记
            if "next" in (j.get("dependencies") or {}) or "next" in (j.get("devDependencies") or {}):
                return "nextjs", j.get("main") or "pages/_app.js"
            return "node", j.get("main") or "index.js"
        except Exception:
            logger.exception("[installer] package.json 解析失败 %s", install_dir)

    # 兜底：纯 SKILL.md / 静态指令
    for md in install_dir.glob("*.md"):
        return "static-instruction", md.name
    return "static-instruction", None


# ─────────────────────────── inspect ───────────────────────────
def _resolve_target_version(skill_resp: dict, requested: str | None) -> str:
    """从 /api/v1/skills/{slug} 响应里解析目标 version 字符串。

    ClawHub 响应形如 `{"skill":{"slug":"...","tags":{"latest":"1.0.0"}}, "latestVersion":{"version":"1.0.0","createdAt":..}, "metadata":{...}, ...}`
    优先级：调用方指定 > skill.tags.latest > latestVersion.version > versions[0].version
    """
    if requested:
        return requested
    skill = skill_resp.get("skill") or {}
    tags = skill.get("tags") or {}
    if isinstance(tags, dict) and isinstance(tags.get("latest"), str) and tags["latest"]:
        return tags["latest"]
    lv = skill_resp.get("latestVersion")
    if isinstance(lv, dict) and isinstance(lv.get("version"), str):
        return lv["version"]
    if isinstance(lv, str) and lv:
        return lv
    versions = skill_resp.get("versions") or []
    if isinstance(versions, list) and versions:
        first = versions[0]
        if isinstance(first, dict) and isinstance(first.get("version"), str):
            return first["version"]
    return ""


async def inspect(slug: str, version: str | None = None) -> dict:
    """不下载，只调 ClawHub 元数据 + security summary。"""
    if not SAFE_SLUG_RE.match(slug):
        raise ValueError(f"非法 slug: {slug!r}")
    skill_resp = await clawhub_client.get_skill(slug)
    target_version = _resolve_target_version(skill_resp, version)

    sec: dict[str, Any] = {}
    if target_version:
        try:
            # package 名 = slug（ClawHub 大部分场景一致）；某些 skill 不是 package → 404 时静默
            sec = await clawhub_client.package_security_summary(slug, target_version)
        except clawhub_client.ClawHubNotFound:
            logger.info("[installer] %s 没有对应的 packages security summary（普通 skill）", slug)
        except clawhub_client.ClawHubError as exc:
            logger.warning("[installer] security_summary 失败 %s@%s: %s", slug, target_version, exc)

    # ClawHub 在 skill_resp 里也可能附 moderation 信息
    moderation = skill_resp.get("moderation") or {}
    if not sec and moderation:
        sec = {"trust": {"scanStatus": moderation.get("verdict"),
                          "moderationState": moderation.get("verdict"),
                          "blockedFromDownload": moderation.get("isMalwareBlocked", False)}}

    high_risk = sorted(set(clawhub_client.high_risk_tags_in({"security": sec.get("trust", {})})))
    blocked = clawhub_client.is_blocked(sec)
    return {
        "slug": slug,
        "version": target_version,
        "skill": skill_resp,
        "security": sec,
        "high_risk_tags": high_risk,
        "blocked": blocked,
    }


# ─────────────────────────── install ───────────────────────────
async def install(
    db: AsyncSession,
    *,
    slug: str,
    version: str | None = None,
    mission_id: uuid.UUID | None = None,
    force_high_risk: bool = False,
) -> RemoteSkillInstall:
    """下载 + 解压 + 写 DB。

    force_high_risk=True 时跳过 capability 红线；调用方应在弹 approval 后才传 True。
    """
    if not SAFE_SLUG_RE.match(slug):
        raise ValueError(f"非法 slug: {slug!r}")

    insp = await inspect(slug, version)
    target_version = insp["version"]
    if not target_version:
        raise ValueError(f"无法从 ClawHub 解析 {slug} 的 version")
    if insp["blocked"]:
        raise ClawhubInstallBlocked(
            f"ClawHub 标记 {slug}@{target_version} blockedFromDownload；拒绝安装"
        )
    if insp["high_risk_tags"] and not force_high_risk:
        raise ClawhubInstallNeedsApproval(
            "存在高危 capability 标签，需用户先批准：" + ",".join(insp["high_risk_tags"])
        )

    # 已存在 install? 复用
    existing_row = await db.execute(
        select(RemoteSkillInstall).where(
            RemoteSkillInstall.clawhub_slug == slug,
            RemoteSkillInstall.clawhub_version == target_version,
        )
    )
    rec = existing_row.scalar_one_or_none()
    if rec is not None:
        logger.info("[installer] %s@%s 已安装 → 复用 (id=%s)", slug, target_version, rec.id)
        return rec

    # 下载 ZIP
    zip_bytes = await clawhub_client.download_skill_zip(slug, target_version)
    if not isinstance(zip_bytes, (bytes, bytearray)):
        raise ValueError(f"download_skill_zip 返回非 bytes: type={type(zip_bytes)}")

    target_dir = install_dir_for(slug, target_version)
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # 防 zip slip：所有 entry 必须落在 target_dir 内
            for name in zf.namelist():
                dest = (target_dir / name).resolve()
                if not str(dest).startswith(str(target_dir.resolve())):
                    raise ValueError(f"非法 zip 条目（zip-slip）：{name}")
            zf.extractall(target_dir)
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise

    runtime_kind, entrypoint = detect_runtime_kind(target_dir)
    # M6 暂不生成 python wrapper（M7+ 接入）；占位 None
    capability_tags = sorted({
        *(insp.get("security", {}).get("trust", {}).get("capabilityTags") or []),
        *(insp.get("high_risk_tags") or []),
    })

    rec = RemoteSkillInstall(
        mission_id=mission_id,
        clawhub_slug=slug,
        clawhub_version=target_version,
        runtime_kind=runtime_kind,
        install_dir=str(target_dir),
        entrypoint=entrypoint,
        python_wrapper_path=None,
        capability_tags=capability_tags,
        security_summary=insp.get("security") or {},
    )
    db.add(rec)
    await db.flush()  # 拿到 id

    # 镜像到 skills 表（让 Agent 能绑）
    mirror = await _ensure_skill_mirror(db, rec, insp.get("skill") or {})
    rec.local_skill_id = mirror.id
    await db.commit()
    await db.refresh(rec)
    logger.info(
        "[installer] 安装完成 %s@%s kind=%s entry=%s dir=%s",
        slug, target_version, runtime_kind, entrypoint, target_dir,
    )
    return rec


async def _ensure_skill_mirror(
    db: AsyncSession, rec: RemoteSkillInstall, skill_meta: dict
) -> Skill:
    # slug 在 skills 表全局唯一；用 `clawhub-{slug}-{version}` 避开冲突
    # 注意 _safe_slug（不是 _safe_name）—— skills.slug 列规则 `^[a-z0-9][a-z0-9_-]*$` 不含点号
    mirror_slug = _safe_slug(f"clawhub-{rec.clawhub_slug}-{rec.clawhub_version}")
    existing_row = await db.execute(select(Skill).where(Skill.slug == mirror_slug))
    existing = existing_row.scalar_one_or_none()
    name = (skill_meta or {}).get("displayName") or rec.clawhub_slug
    description = (skill_meta or {}).get("summary") or f"ClawHub: {rec.clawhub_slug}"
    if existing is not None:
        existing.name = name
        existing.description = description[:512]
        existing.version = rec.clawhub_version[:32]
        existing.builtin_ref = "remote_skill_invoke"
        existing.is_enabled = True
        existing.category = "installer"
        # ADR-009 follow-up · ClawHub 装的 MCP/工具是业务执行件 → 归 worker（不污染 super=PM）
        existing.scope = "worker"
        existing.intent = "io"
        return existing
    s = Skill(
        name=name[:128],
        slug=mirror_slug[:128],
        description=description[:512],
        version=rec.clawhub_version[:32],
        category="installer",
        skill_type="tool_builtin",
        content_md=f"## ClawHub Skill {rec.clawhub_slug}@{rec.clawhub_version}\n"
        f"- runtime_kind: `{rec.runtime_kind}`\n"
        f"- install_dir: `{rec.install_dir}`\n"
        f"- capability_tags: {rec.capability_tags}\n",
        builtin_ref="remote_skill_invoke",
        config_schema={"remote_install_id": {"type": "string"}},
        is_enabled=True,
        is_builtin=False,
        scope="worker",  # 执行件 → worker
        intent="io",
    )
    db.add(s)
    await db.flush()
    return s


# ─────────────────────────── uninstall ───────────────────────────
async def uninstall(db: AsyncSession, install_id: uuid.UUID) -> bool:
    rec = await db.get(RemoteSkillInstall, install_id)
    if rec is None:
        return False
    # 删本地目录
    with suppress(Exception):
        p = Path(rec.install_dir)
        if p.exists() and str(p.resolve()).startswith(str(install_root().resolve())):
            shutil.rmtree(p, ignore_errors=True)
    # 删 mirror skill
    if rec.local_skill_id:
        ms = await db.get(Skill, rec.local_skill_id)
        if ms is not None:
            await db.delete(ms)
    await db.delete(rec)
    await db.commit()
    return True


# ─────────────────────────── list ───────────────────────────
async def list_installed(
    db: AsyncSession, *, mission_id: uuid.UUID | None = None
) -> Sequence[RemoteSkillInstall]:
    stmt = select(RemoteSkillInstall).order_by(RemoteSkillInstall.installed_at.desc())
    if mission_id is not None:
        stmt = stmt.where(RemoteSkillInstall.mission_id == mission_id)
    return (await db.execute(stmt)).scalars().all()


# ─────────────────────────── 错误类型 ───────────────────────────
class ClawhubInstallBlocked(Exception):
    pass


class ClawhubInstallNeedsApproval(Exception):
    """高危 capability 必须先 approval。"""
