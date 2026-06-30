"""worker token 用量汇总（修 worker_invocation_log.tokens 恒空）。"""
from app.domain.dispatch.usage import sum_message_usage


class _Msg:
    def __init__(self, usage_metadata=None, response_metadata=None):
        if usage_metadata is not None:
            self.usage_metadata = usage_metadata
        if response_metadata is not None:
            self.response_metadata = response_metadata


def test_empty():
    assert sum_message_usage([]) == (0, 0)
    assert sum_message_usage(None) == (0, 0)


def test_usage_metadata_langchain():
    msgs = [
        _Msg(usage_metadata={"input_tokens": 100, "output_tokens": 30}),
        _Msg(usage_metadata={"input_tokens": 50, "output_tokens": 20}),
    ]
    assert sum_message_usage(msgs) == (150, 50)


def test_openai_response_metadata_fallback():
    msgs = [_Msg(response_metadata={"token_usage": {"prompt_tokens": 200, "completion_tokens": 40}})]
    assert sum_message_usage(msgs) == (200, 40)


def test_no_double_count_prefers_usage_metadata():
    # 同时有两种 → 优先 usage_metadata，不重复计
    msgs = [_Msg(usage_metadata={"input_tokens": 10, "output_tokens": 5},
                 response_metadata={"token_usage": {"prompt_tokens": 999, "completion_tokens": 999}})]
    assert sum_message_usage(msgs) == (10, 5)


def test_human_messages_contribute_zero():
    msgs = [_Msg(), _Msg(usage_metadata={"input_tokens": 7, "output_tokens": 3})]
    assert sum_message_usage(msgs) == (7, 3)
