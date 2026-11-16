"""Data shapes for the stale-answer detector."""

from dataclasses import dataclass
from enum import Enum

from core.llm import LLMCall
from core.search import Source


class Verdict(str, Enum):
    CURRENT = "current"
    OUTDATED = "outdated"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class Claim:
    """A factual statement pulled out of the answer being checked."""

    text: str
    category: str
    search_query: str


@dataclass(frozen=True)
class Verification:
    """What live sources say about one claim."""

    verdict: Verdict
    confidence: float
    explanation: str
    current_value: str
    supporting_urls: tuple[str, ...]


@dataclass(frozen=True)
class ClaimResult:
    claim: Claim
    verification: Verification
    sources: tuple[Source, ...]
    freshness_score: int


def evidence_basis(result: ClaimResult) -> str:
    """What kind of source the verdict rests on, for display."""
    used = [s for s in result.sources if s.url in result.verification.supporting_urls]
    if not used:
        return "No supporting source"
    if any(s.official for s in used):
        return "Official source"
    if any(s.published for s in used):
        return "Dated news"
    return "Undated web pages"


@dataclass(frozen=True)
class Report:
    results: tuple[ClaimResult, ...]
    overall_score: int | None
    calls: tuple[LLMCall, ...]
    warnings: tuple[str, ...]
