"""Gateway client tests with HTTP faked out."""

import pytest

from core import llm
from core.config import ModelRoute

ROUTE = ModelRoute("groq/fast", "gemini/fast")
OK_BODY = {
    "choices": [{"message": {"content": '{"ok": true}'}}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    "extra_fields": {
        "routing_info": {"provider": "gemini", "model": "fast", "is_fallback": True}
    },
}


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = str(body)

    def json(self):
        return self._body


def install(monkeypatch, responses):
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append({"url": url, "json": json, "headers": headers})
        return responses[min(len(calls), len(responses)) - 1]

    monkeypatch.setattr(llm.requests, "post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    return calls


def test_request_carries_virtual_key_and_fallback_model(monkeypatch):
    calls = install(monkeypatch, [FakeResponse(200, OK_BODY)])

    parsed, call = llm.chat_json("http://gw", "sk-bf-test", ROUTE, "sys", "user")

    assert parsed == {"ok": True}
    assert calls[0]["headers"] == {"x-bf-vk": "sk-bf-test"}
    assert calls[0]["json"]["fallbacks"] == ["gemini/fast"]
    assert call.is_fallback is True
    assert call.served_by == "gemini/fast"


def test_rate_limited_call_is_retried_and_then_succeeds(monkeypatch):
    calls = install(monkeypatch, [FakeResponse(429), FakeResponse(200, OK_BODY)])

    parsed, _ = llm.chat_json("http://gw", "sk-bf-test", ROUTE, "sys", "user")

    assert parsed == {"ok": True}
    assert len(calls) == 2


def test_persistent_rate_limit_raises_after_all_retries(monkeypatch):
    calls = install(monkeypatch, [FakeResponse(429)])

    with pytest.raises(llm.LLMError, match="HTTP 429"):
        llm.chat_json("http://gw", "sk-bf-test", ROUTE, "sys", "user")

    assert len(calls) == 1 + len(llm.RETRY_DELAYS_SECONDS)


def test_other_errors_are_not_retried(monkeypatch):
    calls = install(monkeypatch, [FakeResponse(403)])

    with pytest.raises(llm.LLMError, match="HTTP 403"):
        llm.chat_json("http://gw", "sk-bf-test", ROUTE, "sys", "user")

    assert len(calls) == 1
