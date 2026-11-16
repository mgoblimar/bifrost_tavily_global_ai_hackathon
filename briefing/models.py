"""Data shapes for the pre-meeting briefing."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from core.llm import LLMCall
from core.search import Source
from stale_detector.models import Report


class Status(str, Enum):
    VERIFIED = "verified"
    UNCERTAIN = "uncertain"
    DISPUTED = "disputed"


@dataclass(frozen=True)
class MeetingRequest:
    subject: str
    meeting_time: datetime
    purpose: str
    notes: str = ""
    talking_points: str = ""
    trusted_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class Development:
    """One thing that happened in the research window."""

    headline: str
    detail: str
    category: str
    happened_on: str
    source_numbers: tuple[int, ...]
    status: Status
    status_reason: str
    freshness_score: int | None = None


@dataclass(frozen=True)
class Briefing:
    request: MeetingRequest
    window_start: date
    window_end: date
    summary: str
    developments: tuple[Development, ...]
    open_questions: tuple[str, ...]
    sources: tuple[Source, ...]
    calls: tuple[LLMCall, ...]
    warnings: tuple[str, ...]
    talking_points: Report | None = None
