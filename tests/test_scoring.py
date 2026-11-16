from datetime import date, timedelta

from core.search import Source, parse_published
from stale_detector.models import Verdict
from stale_detector.scoring import (
    evidence_quality,
    freshness_score,
    overall_score,
    recency,
)

TODAY = date(2026, 11, 16)


def make_source(days_old: int | None) -> Source:
    published = None if days_old is None else TODAY - timedelta(days=days_old)
    return Source(title="t", url=f"https://example.com/{days_old}", snippet="", published=published)


def test_recency_is_one_for_a_source_published_today():
    assert recency(TODAY, TODAY) == 1.0


def test_recency_halves_after_one_half_life():
    assert recency(TODAY - timedelta(days=180), TODAY) == 0.5


def test_recency_is_neutral_when_the_date_is_unknown():
    assert recency(None, TODAY) == 0.5


def test_recency_treats_future_dates_as_today():
    assert recency(TODAY + timedelta(days=5), TODAY) == 1.0


def test_evidence_quality_is_zero_without_sources():
    assert evidence_quality((), TODAY) == 0.0


def test_evidence_quality_is_full_for_three_fresh_sources():
    sources = tuple(make_source(0) for _ in range(3))
    assert evidence_quality(sources, TODAY) == 1.0


def test_confident_current_claim_with_strong_evidence_scores_100():
    sources = tuple(make_source(0) for _ in range(3))
    assert freshness_score(Verdict.CURRENT, 1.0, sources, TODAY) == 100


def test_current_claim_with_no_supporting_sources_is_discounted_to_70():
    assert freshness_score(Verdict.CURRENT, 1.0, (), TODAY) == 70


def test_confident_contradicted_claim_scores_zero():
    assert freshness_score(Verdict.CONTRADICTED, 1.0, (make_source(0),), TODAY) == 0


def test_confident_outdated_claim_scores_15():
    assert freshness_score(Verdict.OUTDATED, 1.0, (make_source(0),), TODAY) == 15


def test_unverifiable_claim_scores_50_regardless_of_confidence():
    assert freshness_score(Verdict.UNVERIFIABLE, 0.9, (), TODAY) == 50
    assert freshness_score(Verdict.UNVERIFIABLE, 0.1, (), TODAY) == 50


def test_zero_confidence_outdated_verdict_lands_at_neutral_50():
    assert freshness_score(Verdict.OUTDATED, 0.0, (), TODAY) == 50


def test_out_of_range_confidence_is_clamped():
    assert freshness_score(Verdict.CONTRADICTED, 7.0, (), TODAY) == 0
    assert freshness_score(Verdict.CONTRADICTED, -3.0, (), TODAY) == 50


def test_outdated_always_scores_below_current():
    sources = (make_source(400),)
    current = freshness_score(Verdict.CURRENT, 0.6, sources, TODAY)
    outdated = freshness_score(Verdict.OUTDATED, 0.6, sources, TODAY)
    assert outdated < current


def test_overall_score_averages_claims():
    assert overall_score((100, 50, 0)) == 50


def test_overall_score_is_none_when_nothing_was_checked():
    assert overall_score(()) is None


def test_parse_published_reads_rfc_2822_dates():
    assert parse_published("Mon, 02 Nov 2026 10:00:00 GMT") == date(2026, 11, 2)


def test_parse_published_reads_iso_dates():
    assert parse_published("2026-11-02T10:00:00Z") == date(2026, 11, 2)


def test_parse_published_returns_none_for_garbage_or_missing():
    assert parse_published("not a date") is None
    assert parse_published(None) is None
