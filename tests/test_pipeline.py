"""Pipeline tests with the gateway and the web faked out."""

from datetime import date

import pytest

from core.config import ModelRoute, Settings
from core.llm import LLMCall, LLMError, parse_json_object
from core.search import SearchError, Source
from stale_detector import pipeline
from stale_detector.models import Verdict

TODAY = date(2026, 11, 16)
SETTINGS = Settings(
    bifrost_url="http://bifrost.test",
    bifrost_virtual_key="sk-bf-test",
    tavily_api_key="test-key",
    fast=ModelRoute("groq/fast", "gemini/fast"),
    strong=ModelRoute("gemini/strong", "groq/strong"),
)
SOURCES = (
    Source("Pricing page", "https://example.com/pricing", "Pro is $25/month.", TODAY),
    Source("Blog", "https://example.com/blog", "Price rose from $20 to $25.", TODAY),
)
ONE_CLAIM = {
    "claims": [
        {"text": "Pro costs $20/month.", "category": "pricing", "search_query": "pro price"}
    ]
}
OUTDATED = {
    "verdict": "outdated",
    "confidence": 0.9,
    "explanation": "Now $25 [1][2].",
    "current_value": "$25/month",
    "supporting_sources": [1, 2, 99, "x"],
}


def fake_call(route: ModelRoute) -> LLMCall:
    return LLMCall("", route.primary, route.primary, False, 10, 5, 1.0)


def install_fakes(monkeypatch, extraction, verification, sources=SOURCES):
    def fake_chat_json(_url, _virtual_key, route, _system, _user):
        payload = extraction if route is SETTINGS.fast else verification
        if isinstance(payload, Exception):
            raise payload
        return payload, fake_call(route)

    def fake_search(_key, _query, _max_results=5, days=None):
        if isinstance(sources, Exception):
            raise sources
        return sources

    monkeypatch.setattr(pipeline, "chat_json", fake_chat_json)
    monkeypatch.setattr(pipeline, "search_web", fake_search)


def test_outdated_claim_gets_a_low_score_and_its_sources(monkeypatch):
    install_fakes(monkeypatch, ONE_CLAIM, OUTDATED)

    report = pipeline.analyze(SETTINGS, "Pro costs $20/month.", TODAY)

    result = report.results[0]
    assert result.verification.verdict is Verdict.OUTDATED
    assert result.verification.current_value == "$25/month"
    assert result.freshness_score < 30
    assert report.overall_score == result.freshness_score
    assert len(report.calls) == 2
    assert report.warnings == ()


def test_invalid_source_numbers_from_the_model_are_ignored(monkeypatch):
    install_fakes(monkeypatch, ONE_CLAIM, OUTDATED)

    report = pipeline.analyze(SETTINGS, "answer", TODAY)

    assert report.results[0].verification.supporting_urls == (
        "https://example.com/pricing",
        "https://example.com/blog",
    )


def test_answer_with_no_time_sensitive_claims_gives_an_empty_report(monkeypatch):
    install_fakes(monkeypatch, {"claims": []}, OUTDATED)

    report = pipeline.analyze(SETTINGS, "2 + 2 = 4", TODAY)

    assert report.results == ()
    assert report.overall_score is None


def test_search_failure_degrades_to_unverifiable_with_a_warning(monkeypatch):
    install_fakes(monkeypatch, ONE_CLAIM, OUTDATED, sources=SearchError("tavily down"))

    report = pipeline.analyze(SETTINGS, "answer", TODAY)

    assert report.results[0].verification.verdict is Verdict.UNVERIFIABLE
    assert report.results[0].freshness_score == 50
    assert report.warnings == ("tavily down",)


def test_no_search_results_is_unverifiable(monkeypatch):
    install_fakes(monkeypatch, ONE_CLAIM, OUTDATED, sources=())

    report = pipeline.analyze(SETTINGS, "answer", TODAY)

    assert report.results[0].verification.verdict is Verdict.UNVERIFIABLE


def test_verification_failure_keeps_sources_and_warns(monkeypatch):
    install_fakes(monkeypatch, ONE_CLAIM, LLMError("gateway down"))

    report = pipeline.analyze(SETTINGS, "answer", TODAY)

    assert report.results[0].verification.verdict is Verdict.UNVERIFIABLE
    assert report.results[0].sources == SOURCES
    assert report.warnings == ("gateway down",)


def test_unknown_verdict_and_bad_confidence_fall_back_safely(monkeypatch):
    weird = {"verdict": "maybe", "confidence": "high", "supporting_sources": None}
    install_fakes(monkeypatch, ONE_CLAIM, weird)

    verification = pipeline.analyze(SETTINGS, "answer", TODAY).results[0].verification

    assert verification.verdict is Verdict.UNVERIFIABLE
    assert verification.confidence == 0.5


def test_extraction_failure_is_raised_to_the_caller(monkeypatch):
    install_fakes(monkeypatch, LLMError("gateway down"), OUTDATED)

    with pytest.raises(LLMError):
        pipeline.analyze(SETTINGS, "answer", TODAY)


def test_malformed_claim_entries_are_skipped(monkeypatch):
    extraction = {"claims": ["just a string", {"text": "  "}, ONE_CLAIM["claims"][0]]}
    install_fakes(monkeypatch, extraction, OUTDATED)

    report = pipeline.analyze(SETTINGS, "answer", TODAY)

    assert [r.claim.text for r in report.results] == ["Pro costs $20/month."]


def test_parse_json_object_tolerates_code_fences():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_object_rejects_non_json():
    with pytest.raises(LLMError):
        parse_json_object("sorry, I cannot help")


def test_served_by_keeps_the_provider_for_models_with_slashes_in_their_name():
    from core.llm import _build_call

    body = {
        "extra_fields": {
            "routing_info": {"provider": "groq", "model": "openai/gpt-oss-20b"}
        }
    }

    assert _build_call(body, "", "x").served_by == "groq/openai/gpt-oss-20b"
