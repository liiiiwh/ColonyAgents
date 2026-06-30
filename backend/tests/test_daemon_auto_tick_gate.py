"""daemon · 区分「自动 cron tick」vs「用户驱动 tick」——决定待审批时是否跳过。

待审批存在时只跳过自动 tick；用户驱动（user_chat / manual / Run Once=None）必须照跑，
否则用户点 Run Once / 批复后续派会被误杀。
"""
from app.services.mission_daemon import _is_auto_tick


def test_cron_interval_event_are_auto():
    assert _is_auto_tick("cron 0 10 * * *") is True
    assert _is_auto_tick("interval 5m") is True
    assert _is_auto_tick("event publish_now") is True
    assert _is_auto_tick("initial_activation") is True


def test_user_driven_and_runonce_not_auto():
    assert _is_auto_tick("user_chat") is False
    assert _is_auto_tick("manual") is False
    assert _is_auto_tick("smoke") is False
    assert _is_auto_tick("user_btw") is False
    assert _is_auto_tick(None) is False  # Run Once 传 payload=None
