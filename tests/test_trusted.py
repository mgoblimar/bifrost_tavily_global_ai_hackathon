"""Trusted-domain parsing and the official-source search path."""

from datetime import date

from core.config import ModelRoute, Settings
from core.search import Source
from core.trusted import is_trusted, parse_domains
from stale_detector import pipeline
from stale_detector.models import (
    Claim,
    ClaimResult,
    Verdict,
    Verification,
    evidence_basis,
)

TODAY = date(2026, 11, 16)
SETTINGS = Settings(
    bifrost_url="http://bifrost.test",
    bifrost_virtual_key="sk-bf-test",
    tavily_api_key="test-key",
    fast=ModelRoute("groq/fast", "gemini/fast"),
    strong=ModelRoute("gemini/strong", "groq/strong"),
)
CLAIM = Claim("Drug X is registered.", "law", "Drug X registration")
OFFICIAL = Source("Registry", "https://www.fda.gov.ph/drug-x", "Registered.", None)
NEWS = Source("News", "https://news.example.com/x", "Reported.", TODAY)
PAGE = Source("Blog", "https://blog.example.com/x", "Says so.", None)


def test_parse_domains_cleans_urls_and_drops_duplicates():
    text = "https://www.FDA.gov.ph/page, doh.gov.ph  fda.gov.ph"

    assert parse_domains(text) == ("fda.gov.ph", "doh.gov.ph")


def test_parse_domains_rejects_anything_that_is_not_a_domain():
    assert parse_domains("not a domain, javascript:alert(1), localhost, a..b") == ()


def test_parse_domains_caps_the_list():
    text = ", ".join(f"site{n}.example.com" for n in range(20))

    assert len(parse_domains(text)) == 8


def test_is_trusted_matches_the_domain_and_its_subdomains_only():
    trusted = ("fda.gov.ph",)

    assert is_trusted("https://fda.gov.ph/a", trusted)
    assert is_trusted("https://verification.fda.gov.ph/a", trusted)
    assert not is_trusted("https://notfda.gov.ph/a", trusted)
    assert not is_trusted("https://fda.gov.ph.evil.example/a", trusted)


def install_search(monkeypatch, calls):
    def fake_search(_key, _query, _max_results=5, days=None, include_domains=(), **_rest):
        calls.append({"days": days, "include_domains": include_domains})
        if include_domains:
            return (OFFICIAL,)
        return (NEWS,) if days is not None else (PAGE, OFFICIAL)

    monkeypatch.setattr(pipeline, "search_web", fake_search)


def test_trusted_sites_are_searched_listed_first_and_marked_official(monkeypatch):
    calls: list[dict] = []
    install_search(monkeypatch, calls)

    sources = pipeline.gather_sources(SETTINGS, CLAIM, ("fda.gov.ph",))

    assert [s.url for s in sources] == [OFFICIAL.url, PAGE.url, NEWS.url]
    assert [s.official for s in sources] == [True, False, False]
    assert {"days": None, "include_domains": ("fda.gov.ph",)} in calls


def test_no_trusted_sites_means_no_extra_search_and_nothing_official(monkeypatch):
    calls: list[dict] = []
    install_search(monkeypatch, calls)

    sources = pipeline.gather_sources(SETTINGS, CLAIM)

    assert len(calls) == 2
    assert not any(s.official for s in sources)


def result_supported_by(*sources: Source) -> ClaimResult:
    urls = tuple(s.url for s in sources)
    verification = Verification(Verdict.CURRENT, 0.9, "", "", urls)
    return ClaimResult(CLAIM, verification, sources, 90)


def test_evidence_basis_prefers_official_then_dated_then_undated():
    official = Source("Registry", OFFICIAL.url, "", None, official=True)

    assert evidence_basis(result_supported_by(official, NEWS)) == "Official source"
    assert evidence_basis(result_supported_by(NEWS, PAGE)) == "Dated news"
    assert evidence_basis(result_supported_by(PAGE)) == "Undated web pages"
    assert evidence_basis(result_supported_by()) == "No supporting source"
