"""V7.0 · 当前时间注入 · 给 agent system prompt 提供「现在几点」。

所有 agent（super/worker, chat/daemon）每次调用 build_agent_executor 时，system prompt
顶部都注入当前时间。cron 自判去重（V7.3）的硬前提：super 必须知道今天几号几点。

时区固定 Asia/Shanghai（cron「晚上7点」= 北京时间），且显式标注让 LLM 无歧义。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Shanghai")
_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def current_time_section(now: datetime | None = None) -> str:
    """返回 system prompt 用的当前时间段（Y-m-d H:i:s + 时区 + 周几）。

    now 可注入固定时间（测试确定性）；不传则取 Asia/Shanghai 当前时刻。
    """
    if now is None:
        now = datetime.now(_TZ)
    else:
        now = now.astimezone(_TZ)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    weekday = _WEEKDAY_CN[now.weekday()]
    return f"## 当前时间\n{stamp} (Asia/Shanghai {weekday})"
