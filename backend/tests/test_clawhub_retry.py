"""clawhub_client._get：瞬时网络错误退避重试 + 末次失败带类型名（不再 error=""）。

背景：代理抖动 / 连接重置时 httpx 抛 ConnectError，其 str() 常为空。
旧 _get 只重试 429、不重试网络错，且把空串透传给下游 → clawhub_inspect 返回 {"ok":false,"error":""}。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest

from app.services import clawhub_client as cc
from app.skills_builtin.channel.clawhub_skills import _fmt_exc

pytestmark = pytest.mark.asyncio


class _Resp:
    def __init__(self, payload):
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}
        self._payload = payload

    def json(self):
        return self._payload


def _fake_client_factory(behaviors):
    """behaviors: list，每次 .get 调用按序消费；元素是 Exception 实例则 raise，否则当返回值。"""
    calls = {"n": 0}

    class _FakeClient:
        async def get(self, path, **kw):
            i = calls["n"]
            calls["n"] += 1
            b = behaviors[i]
            if isinstance(b, Exception):
                raise b
            return b

    @asynccontextmanager
    async def _cm():
        yield _FakeClient()

    return _cm, calls


async def test_get_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(cc.asyncio, "sleep", lambda *_a, **_k: _noop())
    cm, calls = _fake_client_factory([
        httpx.ConnectError(""),          # 1st: 瞬时失败
        httpx.ReadError(""),             # 2nd: 瞬时失败
        _Resp({"results": [{"slug": "zhihu"}]}),  # 3rd: 成功
    ])
    monkeypatch.setattr(cc, "_client", cm)
    out = await cc._get("/api/v1/search")
    assert out == {"results": [{"slug": "zhihu"}]}
    assert calls["n"] == 3  # 重试到第 3 次才成功


async def test_get_exhausts_and_raises_nonempty(monkeypatch):
    monkeypatch.setattr(cc.asyncio, "sleep", lambda *_a, **_k: _noop())
    cm, _ = _fake_client_factory([httpx.ConnectError("")] * 3)
    monkeypatch.setattr(cc, "_client", cm)
    with pytest.raises(cc.ClawHubError) as ei:
        await cc._get("/api/v1/skills/zhihu")
    # 错误信息必须非空且含异常类型名（不再是黑盒 error=""）
    assert "ConnectError" in str(ei.value)


async def _noop():
    return None


def test_fmt_exc_never_empty():
    assert _fmt_exc(httpx.ConnectError("")) == "ConnectError"   # 空串 → 至少类型名
    assert _fmt_exc(ValueError("bad slug")) == "ValueError: bad slug"
