"""Verification API tests with the pipeline faked out."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

import api
from core.config import ConfigError
from core.llm import LLMCall, LLMError
from core.search import Source
from examples.guarded_chat import format_reply
from stale_detector.models import Claim, ClaimResult, Report, Verdict, Verification

OFFICIAL = Source("Releases", "https://python.org/downloads", "3.15", None, official=True)
NEWS = Source("News", "https://news.example.com/py", "3.15 out", date(2026, 10, 7))


def make_report() -> Report:
    claim = Claim("The latest Python is 3.12.", "version", "latest python")
    verification = Verification(
        Verdict.OUTDATED, 0.95, "3.15 is out [1].", "Python 3.15", (OFFICIAL.url,)
    )
    call = LLMCall("", "groq/fast", "gemini/fast", True, 100, 20, 1.0)
    return Report((ClaimResult(claim, verification, (OFFICIAL, NEWS), 15),), 15, (call,), ())


@pytest.fixture
def client(monkeypatch):
    seen = {}

    def fake_analyze(_settings, answer, trusted_domains=(), context=""):
        seen.update(answer=answer, trusted_domains=trusted_domains, context=context)
        return make_report()

    monkeypatch.setattr(api, "load_settings", lambda: object())
    monkeypatch.setattr(api, "analyze", fake_analyze)
    monkeypatch.delenv("CARBON_DATE_API_KEY", raising=False)
    test_client = TestClient(api.app)
    test_client.seen = seen
    return test_client


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_verify_returns_per_claim_freshness_and_sources(client):
    body = client.post("/v1/verify", json={"answer": "The latest Python is 3.12."}).json()

    assert body["overall_freshness"] == 15
    assert body["claims_checked"] == 1
    assert body["stale_claims"] == 1
    claim = body["claims"][0]
    assert claim["verdict"] == "outdated"
    assert claim["is_stale"] is True
    assert claim["current_value"] == "Python 3.15"
    assert claim["evidence_basis"] == "Official source"
    assert claim["sources"][0] == {
        "title": "Releases",
        "url": "https://python.org/downloads",
        "published": None,
        "official": True,
        "used_for_verdict": True,
    }
    assert claim["sources"][1]["published"] == "2026-10-07"
    assert body["gateway"][0]["is_fallback"] is True


def test_trusted_domains_are_cleaned_before_use(client):
    payload = {
        "answer": "x",
        "trusted_domains": ["https://www.FDA.gov.ph/page", "not a domain"],
        "context": "  about drugs  ",
    }

    client.post("/v1/verify", json=payload)

    assert client.seen["trusted_domains"] == ("fda.gov.ph",)
    assert client.seen["context"] == "about drugs"


@pytest.mark.parametrize("payload", [{}, {"answer": ""}, {"answer": "   "}, {"answer": "x" * 9000}])
def test_invalid_answers_are_rejected(client, payload):
    assert client.post("/v1/verify", json=payload).status_code == 422


def test_gateway_failure_returns_502_without_leaking_details(client, monkeypatch):
    def failing(*_args, **_kwargs):
        raise LLMError("Bifrost returned HTTP 500: secret internals")

    monkeypatch.setattr(api, "analyze", failing)

    response = client.post("/v1/verify", json={"answer": "x"})

    assert response.status_code == 502
    assert "secret" not in response.text


def test_missing_configuration_returns_500_without_leaking_details(client, monkeypatch):
    def unconfigured():
        raise ConfigError("TAVILY_API_KEY is missing. Add it to your .env file.")

    monkeypatch.setattr(api, "load_settings", unconfigured)

    response = client.post("/v1/verify", json={"answer": "x"})

    assert response.status_code == 500
    assert "TAVILY" not in response.text


def test_api_key_is_enforced_when_configured(client, monkeypatch):
    monkeypatch.setenv("CARBON_DATE_API_KEY", "s3cret")

    assert client.post("/v1/verify", json={"answer": "x"}).status_code == 401
    wrong = client.post("/v1/verify", json={"answer": "x"}, headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401
    right = client.post("/v1/verify", json={"answer": "x"}, headers={"X-API-Key": "s3cret"})
    assert right.status_code == 200


def test_example_app_flags_the_stale_claim_with_its_correction(client):
    report = client.post("/v1/verify", json={"answer": "x"}).json()

    reply = format_reply("The latest Python is 3.12.", report)

    assert "1 of 1 claims are out of date" in reply
    assert "Now:  Python 3.15" in reply
    assert "Source: https://python.org/downloads" in reply
