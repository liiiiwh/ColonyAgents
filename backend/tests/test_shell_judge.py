"""ADR-010 R3 · LLM 安全门输出解析（纯逻辑）。

快模型返回常含噪声/代码围栏；解析必须稳，且**解析失败一律 default-deny**
（误判为 allow 是灾难）。
"""
from app.services.shell_judge import parse_judge_response


def test_garbage_defaults_deny():
    assert parse_judge_response("我觉得应该没问题吧")["allow"] is False


def test_clean_allow():
    r = parse_judge_response('{"allow": true, "reason": "本地启动命令"}')
    assert r["allow"] is True
    assert "本地启动" in r["reason"]


def test_clean_deny():
    assert parse_judge_response('{"allow": false, "reason": "可疑外联"}')["allow"] is False


def test_fenced_json_extracted():
    r = parse_judge_response('```json\n{"allow": true, "reason": "ok"}\n```')
    assert r["allow"] is True


def test_empty_defaults_deny():
    assert parse_judge_response("")["allow"] is False
    assert parse_judge_response(None)["allow"] is False
