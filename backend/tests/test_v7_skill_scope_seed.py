"""V7.5 · resolve_skill_scope · 内置 skill 的 scope/intent 在 seed 时就设对。

之前 migration 049 只 backfill 现有 prod 行；fresh install 的 seed 不设 scope → scope=NULL
→ auto-bind 当 'all' → super-only 工具被绑到 worker（R2-4 保护在新装上静默失效）。
修：seed 用 resolve_skill_scope 统一设 scope。
"""
from __future__ import annotations

import pytest


def test_super_only_dispatch_skills():
    from app.skills_builtin.skill_scope import resolve_skill_scope
    for slug in ("invoke_worker", "request_approval", "request_new_capability",
                 "list_workers", "request_structured_input"):
        scope, intent = resolve_skill_scope(slug, "custom")
        assert scope == "super", slug


def test_worker_io_skills():
    from app.skills_builtin.skill_scope import resolve_skill_scope
    scope, intent = resolve_skill_scope("return_result", "custom")
    assert scope == "worker"


def test_builder_category_skills():
    from app.skills_builtin.skill_scope import resolve_skill_scope
    scope, _ = resolve_skill_scope("some_builder_tool", "builder")
    assert scope == "builder"


def test_default_is_all():
    from app.skills_builtin.skill_scope import resolve_skill_scope
    scope, intent = resolve_skill_scope("knowledge_search", "general")
    assert scope == "all"
