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


@dataclass(frozen=True)
class Report:
    results: tuple[ClaimResult, ...]
    overall_score: int | None
    calls: tuple[LLMCall, ...]
    warnings: tuple[str, ...]
