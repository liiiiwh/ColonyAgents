"""ADR-009 G6 · 受限模板化 skill 创建（纯校验）+ P5 缺 skill 优雅降级。

不允许运行时跑任意代码：只支持白名单模板，参数化生成 skill 行（builtin_ref 指向通用执行器）。
"""
from __future__ import annotations

import pytest


def test_known_templates_listed():
    from app.domain.builder.skill_template import SKILL_TEMPLATES
    assert "http_api_call" in SKILL_TEMPLATES
    assert "prompt_macro" in SKILL_TEMPLATES


def test_validate_template_request_ok():
    from app.domain.builder.skill_template import validate_template_request
    err = validate_template_request(
        template="http_api_call",
        slug="weather_api",
        config={"method": "GET", "url_template": "https://api/x?q={q}"},
    )
    assert err is None


def test_reject_unknown_template():
    from app.domain.builder.skill_template import validate_template_request
    err = validate_template_request(template="run_python", slug="x", config={})
    assert err is not None
    assert "模板" in err or "template" in err.lower()


def test_reject_missing_required_config():
    from app.domain.builder.skill_template import validate_template_request
    err = validate_template_request(template="http_api_call", slug="weather_api", config={"method": "GET"})
    assert err is not None
    assert "url_template" in err


def test_reject_bad_slug():
    from app.domain.builder.skill_template import validate_template_request
    err = validate_template_request(
        template="prompt_macro", slug="Bad Slug!", config={"prompt_template": "say {x}"},
    )
    assert err is not None
    assert "slug" in err.lower()


def test_render_skill_row_fields():
    from app.domain.builder.skill_template import render_skill_row
    row = render_skill_row(
        template="http_api_call", slug="weather_api", name="Weather",
        config={"method": "GET", "url_template": "https://api/x?q={q}"},
    )
    assert row["slug"] == "weather_api"
    assert row["builtin_ref"]  # 指向通用执行器
    assert row["config"]["template"] == "http_api_call"
    assert row["skill_type"]  # 有类型
