"""Freshness score: a 0-100 number per claim, computed in plain code.

The model only supplies a verdict and a confidence. The score itself is
deterministic so it can be explained, tested and tuned:

1. Each verdict has a base value (current = 1, contradicted = 0).
2. Confidence pulls that value toward the neutral midpoint, so an unsure
   "current" and an unsure "outdated" both land near 50.
3. A "current" claim is then discounted when the evidence is thin or old.
"""

from datetime import date

from core.search import Source
from stale_detector.models import Verdict

VERDICT_BASE = {
    Verdict.CURRENT: 1.0,
    Verdict.UNVERIFIABLE: 0.5,
    Verdict.OUTDATED: 0.15,
    Verdict.CONTRADICTED: 0.0,
}
NEUTRAL = 0.5
EVIDENCE_FLOOR = 0.7  # a "current" claim keeps at least this share of its score
SOURCES_FOR_FULL_AGREEMENT = 3
RECENCY_HALF_LIFE_DAYS = 180
UNKNOWN_DATE_RECENCY = 0.5


def recency(published: date | None, today: date) -> float:
    """1.0 for a source published today, halving every RECENCY_HALF_LIFE_DAYS."""
    if published is None:
        return UNKNOWN_DATE_RECENCY
    age_days = max((today - published).days, 0)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def evidence_quality(supporting: tuple[Source, ...], today: date) -> float:
    """0-1: how many sources back the verdict and how recent they are."""
    if not supporting:
        return 0.0
    agreement = min(len(supporting), SOURCES_FOR_FULL_AGREEMENT) / (
        SOURCES_FOR_FULL_AGREEMENT
    )
    average_recency = sum(recency(s.published, today) for s in supporting) / len(
        supporting
    )
    return 0.5 * agreement + 0.5 * average_recency


def freshness_score(
    verdict: Verdict,
    confidence: float,
    supporting: tuple[Source, ...],
    today: date,
) -> int:
    confidence = min(max(confidence, 0.0), 1.0)
    value = NEUTRAL + (VERDICT_BASE[verdict] - NEUTRAL) * confidence
    if verdict is Verdict.CURRENT:
        quality = evidence_quality(supporting, today)
        value *= EVIDENCE_FLOOR + (1 - EVIDENCE_FLOOR) * quality
    return round(100 * value)


def overall_score(scores: tuple[int, ...]) -> int | None:
    """Average freshness across claims; None when nothing was checked."""
    if not scores:
        return None
    return round(sum(scores) / len(scores))
