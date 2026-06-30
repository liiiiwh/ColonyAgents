"""ADR-009 G6 · 受限模板化 skill 创建（纯）。

**不允许运行时跑任意代码**。Builder 只能从白名单模板参数化生成 skill：
- http_api_call : 调一个 HTTP API（config: method, url_template, headers?）
- mcp_proxy     : 代理一个已注册 MCP server 的某工具（config: mcp_server_id, tool_name）
- prompt_macro  : 把一段 prompt 模板 + 子模型调用封成一个 skill（config: prompt_template, role?）

生成的 skill 行 builtin_ref 指向对应的通用执行器（已存在的内置工具），config 驱动行为，
不引入任意新代码。实际落库 + 通用执行器接线在 services 层。
"""
from __future__ import annotations

import re

# template -> {required_config: [...], builtin_ref, skill_type}
SKILL_TEMPLATES: dict[str, dict] = {
    "http_api_call": {
        "required_config": ["method", "url_template"],
        "builtin_ref": "templated_http_call",
        "skill_type": "templated",
    },
    "mcp_proxy": {
        "required_config": ["mcp_server_id", "tool_name"],
        "builtin_ref": "templated_mcp_proxy",
        "skill_type": "templated",
    },
    "prompt_macro": {
        "required_config": ["prompt_template"],
        "builtin_ref": "templated_prompt_macro",
        "skill_type": "templated",
    },
}

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


def validate_template_request(*, template: str, slug: str, config: dict) -> str | None:
    """校验模板创建请求。合法返回 None，否则返回错误信息（给 Builder LLM 看）。"""
    tpl = SKILL_TEMPLATES.get(template)
    if tpl is None:
        return (
            f"未知 skill 模板 {template!r}；只支持白名单模板："
            f"{sorted(SKILL_TEMPLATES)}（不允许运行任意代码）。"
        )
    if not _SLUG_RE.match(slug or ""):
        return f"slug 非法 {slug!r}：须小写字母开头、仅含 a-z0-9_、长度 2-63。"
    missing = [k for k in tpl["required_config"] if k not in (config or {})]
    if missing:
        return f"模板 {template} 缺必填 config 字段：{missing}"
    return None


def render_skill_row(*, template: str, slug: str, name: str, config: dict) -> dict:
    """渲染待落库的 skill 行（不含 DB id）。调用前应先 validate_template_request。"""
    tpl = SKILL_TEMPLATES[template]
    return {
        "slug": slug,
        "name": name or slug,
        "skill_type": tpl["skill_type"],
        "builtin_ref": tpl["builtin_ref"],
        "config": {"template": template, **(config or {})},
    }
