"""微信 Clawbot (ilink bot) HTTP API 客户端。

参考：https://github.com/liiiiwh/weixin-clawbot-skill 的 SKILL.md
API base: https://ilinkai.weixin.qq.com
认证：Bearer <bot_token> + AuthorizationType: ilink_bot_token + X-WECHAT-UIN

本模块封装：
- get_qrcode / poll_qrcode_status — 扫码登录
- send_text — 发文本消息（必带 context_token）
- get_updates — 长轮询拉用户回复
- get_config — 拉 typing_ticket

只支持文本（审批场景够了；图片/语音 M+ 再扩）。
"""

from __future__ import annotations

import base64
import logging
import random
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ILINK_DEFAULT_BASE = "https://ilinkai.weixin.qq.com"
GET_UPDATES_TIMEOUT_SEC = 40.0  # SKILL 说服务端 longpolling_timeout_ms ≈ 35s，给点 buffer
NORMAL_TIMEOUT_SEC = 15.0


def _wechat_uin_header() -> str:
    """X-WECHAT-UIN: base64 of random uint32 decimal string."""
    n = str(random.randint(1, 0xFFFFFFFF))
    return base64.b64encode(n.encode("ascii")).decode("ascii")


def _headers(token: str | None = None) -> dict:
    h: dict = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _wechat_uin_header(),
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def get_qrcode(base_url: str | None = None) -> dict:
    """Step 1：拉登录二维码。

    返回 {qrcode_session, qrcode_img_url, qrcode_inline_img_url}
    - qrcode_img_url: ilink 官方页面 URL（浏览器打开渲染二维码）
    - qrcode_inline_img_url: 用 api.qrserver.com 公共服务把 qrcode_img_url 渲成 PNG 图片 URL，
      可直接在 markdown 里 `![](url)` 嵌入到 Builder Chat 审批卡 / observe 页让用户扫码
    """
    import urllib.parse

    base = base_url or ILINK_DEFAULT_BASE
    async with httpx.AsyncClient(timeout=NORMAL_TIMEOUT_SEC) as c:
        r = await c.get(
            f"{base}/ilink/bot/get_bot_qrcode",
            params={"bot_type": 3},
            headers=_headers(),
        )
        r.raise_for_status()
        d = r.json()
        qr_url = d.get("qrcode_img_content") or ""
        inline = (
            f"https://api.qrserver.com/v1/create-qr-code/?size=280x280&margin=8&data="
            + urllib.parse.quote(qr_url, safe="")
            if qr_url
            else ""
        )
        return {
            "qrcode_session": d.get("qrcode") or "",
            "qrcode_img_url": qr_url,
            "qrcode_inline_img_url": inline,
        }


async def poll_qrcode_status(
    qrcode_session: str, base_url: str | None = None
) -> dict:
    """Step 2：轮询扫码状态。返回 {status, bot_token?, baseurl?, ilink_bot_id?, ilink_user_id?}。

    status ∈ wait / scaned / confirmed / expired。
    长轮询调用：每个 HTTP 请求超时 35s，多次调用直到 confirmed/expired。
    """
    base = base_url or ILINK_DEFAULT_BASE
    headers = _headers()
    headers["iLink-App-ClientVersion"] = "1"
    async with httpx.AsyncClient(timeout=GET_UPDATES_TIMEOUT_SEC) as c:
        r = await c.get(
            f"{base}/ilink/bot/get_qrcode_status",
            params={"qrcode": qrcode_session},
            headers=headers,
        )
        r.raise_for_status()
        d = r.json()
        out: dict[str, Any] = {"status": d.get("status") or "wait"}
        for k in ("bot_token", "ilink_bot_id", "baseurl", "ilink_user_id"):
            if d.get(k):
                out[k] = d[k]
        return out


async def send_text(
    *,
    token: str,
    base_url: str,
    to_user_id: str,
    text: str,
    context_token: str = "",
) -> dict:
    """发文本消息。context_token 必传（从上一次入站消息拿）。

    如果没有 context_token（首次主动推送）也试发——某些场景服务端允许，但通常会被拒。
    """
    payload = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": uuid.uuid4().hex,
            "message_type": 2,  # BOT → USER
            "message_state": 2,  # FINISH
            "context_token": context_token,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        }
    }
    async with httpx.AsyncClient(timeout=NORMAL_TIMEOUT_SEC) as c:
        r = await c.post(
            f"{base_url}/ilink/bot/sendmessage",
            json=payload,
            headers=_headers(token),
        )
        r.raise_for_status()
        return r.json()


async def get_updates(
    *,
    token: str,
    base_url: str,
    sync_buffer: str = "",
) -> dict:
    """长轮询拉用户消息。返回 {msgs: [...], get_updates_buf, errcode}。

    长连接：服务端会 hold 住直到有新消息或 ~35s 超时。
    调用方应循环调；新拉到的 get_updates_buf 持久化作为下次入参。
    """
    payload = {"get_updates_buf": sync_buffer}
    async with httpx.AsyncClient(timeout=GET_UPDATES_TIMEOUT_SEC) as c:
        try:
            r = await c.post(
                f"{base_url}/ilink/bot/getupdates",
                json=payload,
                headers=_headers(token),
            )
            r.raise_for_status()
            return r.json()
        except httpx.TimeoutException:
            # 长轮询无消息超时是正常的；返回空让外层立即重发
            return {"msgs": [], "get_updates_buf": sync_buffer, "errcode": 0}


def parse_text_messages(updates_resp: dict) -> list[dict]:
    """从 get_updates 返回值抽出所有文本消息。

    返回 [{from_user_id, text, context_token, message_id, create_time_ms}, ...]
    """
    out: list[dict] = []
    for m in updates_resp.get("msgs") or []:
        items = m.get("item_list") or []
        # 找第一个文本 item
        text_item = next(
            (i.get("text_item", {}) for i in items if i.get("type") == 1 and i.get("text_item")),
            None,
        )
        if not text_item:
            continue
        text = (text_item.get("text") or "").strip()
        if not text:
            continue
        out.append(
            {
                "from_user_id": m.get("from_user_id") or "",
                "text": text,
                "context_token": m.get("context_token") or "",
                "message_id": m.get("message_id"),
                "create_time_ms": m.get("create_time_ms"),
            }
        )
    return out
