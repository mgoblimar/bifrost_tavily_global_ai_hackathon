"""Briefing tests with the gateway, the web and the detector faked out."""

from datetime import date, datetime, timedelta

from briefing import pipeline
from briefing.models import MeetingRequest, Status
from briefing.render import to_markdown
from core.config import ModelRoute, Settings
from core.llm import LLMCall
from core.search import SearchError, Source
from stale_detector.models import Claim, ClaimResult, Report, Verdict, Verification

TODAY = date(2026, 11, 16)
SETTINGS = Settings(
    bifrost_url="http://bifrost.test",
    bifrost_virtual_key="sk-bf-test",
    tavily_api_key="test-key",
    fast=ModelRoute("groq/fast", "gemini/fast"),
    strong=ModelRoute("gemini/strong", "groq/strong"),
)
REQUEST = MeetingRequest(
    subject="Acme Corp",
    meeting_time=datetime(2026, 11, 18, 14, 0),
    purpose="Sales call",
)
RECENT = Source("Acme launches X", "https://a.example/1", "Acme launched X.", TODAY)
OLDER = Source(
    "Acme hires CFO", "https://b.example/2", "New CFO.", TODAY - timedelta(days=10)
)
TOO_OLD = Source(
    "Acme in 2025", "https://c.example/3", "Old news.", TODAY - timedelta(days=90)
)
UNDATED = Source("Acme profile", "https://d.example/4", "About Acme.", None)
DRAFT = {
    "summary": "Acme is a widget maker.",
    "developments": [
        {
            "headline": "Acme launches X",
            "detail": "Launched on Monday.",
            "category": "launch",
            "date": "2026-11-16",
            "sources": [1, 2],
            "confidence": "verified",
            "reason": "two sources agree",
        },
        {
            "headline": "Rumoured acquisition",
            "detail": "A blog claims talks.",
            "category": "news",
            "date": "",
            "sources": [2, 99],
            "confidence": "uncertain",
            "reason": "single blog",
        },
        {"headline": "No citation", "detail": "x", "sources": []},
        "not a dict",
    ],
    "open_questions": ["How is X selling?", "  "],
}


def fake_call() -> LLMCall:
    return LLMCall("", "gemini/strong", "gemini/strong", False, 10, 5, 1.0)


def install(monkeypatch, sources=(RECENT, OLDER), draft=DRAFT, verdict=Verdict.CURRENT):
    def fake_search(_key, _query, _max_results=5, **_options):
        if isinstance(sources, Exception):
            raise sources
        return sources

    def fake_chat_json(_url, _virtual_key, _route, _system, _user):
        return draft, fake_call()

    def fake_check_claim(_settings, claim: Claim, _today, _trusted_domains=()):
        verification = Verification(verdict, 0.9, "fresh search says so", "", ())
        return ClaimResult(claim, verification, (), 80), fake_call(), None

    monkeypatch.setattr(pipeline, "search_web", fake_search)
    monkeypatch.setattr(pipeline, "chat_json", fake_chat_json)
    monkeypatch.setattr(pipeline, "check_claim", fake_check_claim)


def test_window_is_the_30_days_before_a_past_meeting():
    start, end = pipeline.research_window(date(2026, 11, 10), TODAY)

    assert (start, end) == (date(2026, 10, 11), date(2026, 11, 10))


def test_window_for_a_future_meeting_ends_today():
    start, end = pipeline.research_window(date(2026, 11, 25), TODAY)

    assert (start, end) == (date(2026, 10, 17), TODAY)


def test_sources_outside_the_window_are_dropped_and_newest_come_first(monkeypatch):
    install(monkeypatch, sources=(OLDER, TOO_OLD, RECENT, UNDATED, RECENT))

    briefing = pipeline.build_briefing(SETTINGS, REQUEST, TODAY)

    assert [s.url for s in briefing.sources] == [
        "https://a.example/1",
        "https://b.example/2",
        "https://d.example/4",
    ]


def test_items_without_a_valid_citation_are_dropped(monkeypatch):
    install(monkeypatch)

    briefing = pipeline.build_briefing(SETTINGS, REQUEST, TODAY)

    assert [d.headline for d in briefing.developments] == [
        "Acme launches X",
        "Rumoured acquisition",
    ]
    assert briefing.developments[1].source_numbers == (2,)
    assert briefing.open_questions == ("How is X selling?",)


def test_confirmed_items_stay_verified_and_get_a_freshness_score(monkeypatch):
    install(monkeypatch, verdict=Verdict.CURRENT)

    first, second = pipeline.build_briefing(SETTINGS, REQUEST, TODAY).developments

    assert first.status is Status.VERIFIED
    assert first.freshness_score == 80
    assert second.status is Status.UNCERTAIN


def test_item_contradicted_by_the_cross_check_becomes_disputed(monkeypatch):
    install(monkeypatch, verdict=Verdict.OUTDATED)

    first = pipeline.build_briefing(SETTINGS, REQUEST, TODAY).developments[0]

    assert first.status is Status.DISPUTED
    assert first.status_reason == "fresh search says so"


def test_verified_item_the_cross_check_cannot_confirm_becomes_uncertain(monkeypatch):
    install(monkeypatch, verdict=Verdict.UNVERIFIABLE)

    first = pipeline.build_briefing(SETTINGS, REQUEST, TODAY).developments[0]

    assert first.status is Status.UNCERTAIN


def test_failed_cross_check_keeps_the_drafted_status_and_warns(monkeypatch):
    install(monkeypatch)

    def failing_check(_settings, claim: Claim, _today, _trusted_domains=()):
        verification = Verification(Verdict.UNVERIFIABLE, 0.0, "failed", "", ())
        return ClaimResult(claim, verification, (), 50), None, "gateway down"

    monkeypatch.setattr(pipeline, "check_claim", failing_check)

    briefing = pipeline.build_briefing(SETTINGS, REQUEST, TODAY)

    assert briefing.developments[0].status is Status.VERIFIED
    assert briefing.developments[0].freshness_score is None
    assert briefing.warnings[0] == "Could not cross-check 'Acme launches X': gateway down"


def test_cross_check_can_be_switched_off(monkeypatch):
    install(monkeypatch, verdict=Verdict.OUTDATED)

    briefing = pipeline.build_briefing(SETTINGS, REQUEST, TODAY, verify=False)

    assert briefing.developments[0].status is Status.VERIFIED
    assert briefing.developments[0].freshness_score is None
    assert len(briefing.calls) == 1


def test_no_sources_gives_an_empty_briefing_without_calling_the_model(monkeypatch):
    install(monkeypatch, sources=())

    briefing = pipeline.build_briefing(SETTINGS, REQUEST, TODAY)

    assert briefing.developments == ()
    assert briefing.calls == ()
    assert "No dated coverage" in briefing.summary


def test_search_failure_is_reported_as_a_warning(monkeypatch):
    install(monkeypatch, sources=SearchError("tavily down"))

    briefing = pipeline.build_briefing(SETTINGS, REQUEST, TODAY)

    assert briefing.sources == ()
    assert briefing.warnings == ("tavily down",) * len(pipeline.QUERY_TEMPLATES)


def test_markdown_separates_verified_from_uncertain_and_lists_sources(monkeypatch):
    install(monkeypatch)

    text = to_markdown(pipeline.build_briefing(SETTINGS, REQUEST, TODAY))

    assert text.index("## Verified developments") < text.index("## Uncertain or disputed")
    assert "**Acme launches X** (2026-11-16) [1][2]" in text
    assert "## Open questions for the meeting" in text
    assert "1. [Acme launches X](https://a.example/1) (2026-11-16)" in text


def stale_report() -> Report:
    claim = Claim("Acme's CEO is Jo Old.", "leadership", "Acme CEO")
    verification = Verification(Verdict.OUTDATED, 0.9, "Replaced in October.", "Sam New", ())
    return Report((ClaimResult(claim, verification, (), 15),), 15, (), ())


def test_talking_points_are_checked_with_the_subject_as_context(monkeypatch):
    install(monkeypatch)
    seen = {}

    def fake_analyze(_settings, text, _today, trusted_domains, context):
        seen.update(text=text, trusted=trusted_domains, context=context)
        return stale_report()

    monkeypatch.setattr(pipeline, "analyze", fake_analyze)
    request = MeetingRequest(
        subject="Acme Corp",
        meeting_time=REQUEST.meeting_time,
        purpose="Sales call",
        talking_points="Congratulate CEO Jo Old.",
        trusted_domains=("acme.example",),
    )

    briefing = pipeline.build_briefing(SETTINGS, request, TODAY)

    assert briefing.talking_points == stale_report()
    assert seen["text"] == "Congratulate CEO Jo Old."
    assert seen["trusted"] == ("acme.example",)
    assert "Acme Corp" in seen["context"]


def test_no_talking_points_means_no_check(monkeypatch):
    install(monkeypatch)

    assert pipeline.build_briefing(SETTINGS, REQUEST, TODAY).talking_points is None


def test_stale_talking_point_is_flagged_in_the_markdown(monkeypatch):
    install(monkeypatch)
    monkeypatch.setattr(pipeline, "analyze", lambda *_args: stale_report())
    request = MeetingRequest(
        "Acme Corp", REQUEST.meeting_time, "Sales call", talking_points="x"
    )

    text = to_markdown(pipeline.build_briefing(SETTINGS, request, TODAY))

    assert "## Your talking points, checked" in text
    assert "- **Do not say this:** Acme's CEO is Jo Old." in text
    assert "Now: Sam New" in text
