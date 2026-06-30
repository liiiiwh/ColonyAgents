"""R2-2 · _classify_llm_error 抽到 app/services/llm_error_classifier.py。

Pure function：LLM 异常 → (retriable, code, user_msg, request_id)。从 stream_service.py
596-LOC 巨函数里抽出来，让 resilient_llm / chat_handler / 其它 LLM caller 共用同一分类逻辑。
"""
from __future__ import annotations

import pytest


def test_classifies_bad_gateway_as_retriable():
    import litellm
    from app.services.llm_error_classifier import classify_llm_error

    exc = litellm.BadGatewayError(
        message="bad gateway", model="x", llm_provider="x",
    )
    retriable, code, user_msg, _ = classify_llm_error(exc)
    assert retriable is True
    assert code == "BAD_GATEWAY"
    assert "502" in user_msg or "网关" in user_msg


def test_classifies_auth_error_as_non_retriable():
    import litellm
    from app.services.llm_error_classifier import classify_llm_error

    exc = litellm.AuthenticationError(
        message="invalid key", model="x", llm_provider="x",
    )
    retriable, code, user_msg, _ = classify_llm_error(exc)
    assert retriable is False
    assert code == "AUTH_ERROR"


def test_classifies_rate_limit_as_retriable():
    import litellm
    from app.services.llm_error_classifier import classify_llm_error

    exc = litellm.RateLimitError(
        message="429", model="x", llm_provider="x",
    )
    retriable, code, *_ = classify_llm_error(exc)
    assert retriable is True
    assert code == "RATE_LIMIT"


def test_extracts_request_id_from_message():
    import litellm
    from app.services.llm_error_classifier import classify_llm_error

    exc = litellm.BadGatewayError(
        message='{"error": "x", "request_id": "req-abc-123"}',
        model="x", llm_provider="x",
    )
    _, _, _, request_id = classify_llm_error(exc)
    assert request_id == "req-abc-123"


def test_unknown_error_defaults_to_non_retriable():
    from app.services.llm_error_classifier import classify_llm_error

    exc = RuntimeError("totally unexpected")
    retriable, code, *_ = classify_llm_error(exc)
    assert retriable is False
    # 不强求 code 名字，只要它有
    assert isinstance(code, str)
