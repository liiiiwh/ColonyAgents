"""ADR-019(修订)/ADR-020 · SeedLanguage：onboarding 一次性选的语言。

只决定两件事：① 播种哪套语言的系统级 Agent（Builder Supervisor + Worker 优化 super，
见 [[seed-system-agents-bilingual]]）② 设首个 admin 的 UI 语言。

**不是** install gate、**不是**每请求语言源 —— 日常语言是 per-user 的 UILanguage
（前端 `colony-locale` i18n，各用户自切）。这里仅留一个非阻塞记录。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "zh")
SEED_LANGUAGE_KEY = "system_agents_language"


def is_supported_language(lang: str | None) -> bool:
    return lang in SUPPORTED_LANGUAGES


async def get_seed_language(db: AsyncSession) -> str:
    """读系统 Agent 播种语言；未设/非法 → 'en'（基准默认，非 gate 故有默认）。"""
    from app.core import system_settings

    val = await system_settings.get(db, SEED_LANGUAGE_KEY, None)
    return val if is_supported_language(val) else "en"
