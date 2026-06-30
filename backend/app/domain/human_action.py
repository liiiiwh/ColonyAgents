"""ADR-010 R4 · 人类残留卡正文构建。

把一个 pending 的 human-* requirement 渲染成 request_approval 可用的 {title, body, options}。
body 是 markdown（通道支持嵌图，clawbot 已验证）。纯逻辑、可独测；实际投递 + 暂停在
request_human_action 服务里（复用 approval 通道 + 项目 paused）。
"""
from __future__ import annotations

_DONE_OPTION = "我已完成，继续"


def build_human_action_card(
    requirement: dict,
    *,
    server_name: str,
    qr_image_url: str | None = None,
    secret_keys: list[str] | None = None,
    steps: list[str] | None = None,
) -> dict:
    kind = requirement.get("kind")
    rid = requirement.get("id", "")

    if kind == "human-qr":
        body = f"**{server_name}** 需要扫码登录。请用对应 App 扫描下面二维码：\n\n"
        body += f"![登录二维码]({qr_image_url})\n\n" if qr_image_url else "（二维码获取中…）\n\n"
        body += "扫码并在 App 内确认后，点「我已完成，继续」。"
        return {"title": f"[{server_name}] 扫码登录", "body": body, "options": [_DONE_OPTION]}

    if kind == "human-secret":
        keys = secret_keys or [rid.split(":", 1)[-1]]
        body = (f"**{server_name}** 需要你提供密钥/凭证（agent 不会代填）：\n\n"
                + "\n".join(f"- `{k}`" for k in keys)
                + "\n\n请在平台密钥配置里填入后，点「我已完成，继续」。")
        return {"title": f"[{server_name}] 需要密钥", "body": body, "options": [_DONE_OPTION]}

    if kind == "human-tos":
        body = (f"**{server_name}** 需要你接受其服务条款 / 完成授权（agent 不能代你同意）。"
                "\n\n完成后点「我已完成，继续」。")
        return {"title": f"[{server_name}] 需要授权/同意条款", "body": body, "options": [_DONE_OPTION]}

    # instructions（兜底：修不了，给具体步骤）
    body = f"**{server_name}** 需要你手动处理 `{rid}`，步骤：\n\n"
    body += "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps or ["（无具体步骤，请联系管理员）"]))
    body += "\n\n完成后点「我已完成，继续」，我会重新检查。"
    return {"title": f"[{server_name}] 需要手动操作", "body": body, "options": [_DONE_OPTION]}
