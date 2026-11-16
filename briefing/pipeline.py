"""Pre-meeting briefing: research the last 30 days -> draft -> cross-check each item.

The cross-check reuses the stale-answer detector: every development in the
draft is re-verified against a fresh search, so the briefing separates what is
confirmed from what is uncertain or already superseded.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta

from briefing.models import Briefing, Development, MeetingRequest, Status
from briefing.prompts import DRAFT_SYSTEM
from core.config import Settings
from core.llm import LLMCall, LLMError, chat_json
from core.search import SearchError, Source, search_web
from stale_detector.models import Claim, Report, Verdict
from stale_detector.pipeline import analyze, check_claim

WINDOW_DAYS = 30
RESULTS_PER_QUERY = 6
MAX_SOURCES = 14
MAX_DEVELOPMENTS = 5
MAX_OPEN_QUESTIONS = 5
PARALLEL_CHECKS = 3
QUERY_TEMPLATES = (
    "{subject}",
    "{subject} announcement OR launch OR partnership",
    "{subject} appointed OR hired OR resigns OR funding OR lawsuit",
)


def research_window(meeting_day: date, today: date) -> tuple[date, date]:
    """The 30 days before the meeting, never reaching past today."""
    window_end = min(meeting_day, today)
    return window_end - timedelta(days=WINDOW_DAYS), window_end


def research(
    settings: Settings, subject: str, window_start: date, window_end: date
) -> tuple[tuple[Source, ...], tuple[str, ...]]:
    """Dated news about the subject inside the window, newest first."""
    found: dict[str, Source] = {}
    warnings: list[str] = []
    for template in QUERY_TEMPLATES:
        try:
            results = search_web(
                settings.tavily_api_key,
                template.format(subject=subject),
                RESULTS_PER_QUERY,
                depth="basic",
                start_date=window_start,
                end_date=window_end,
            )
        except SearchError as exc:
            warnings.append(str(exc))
            continue
        for source in results:
            if in_window(source, window_start, window_end):
                found.setdefault(source.url, source)

    newest_first = sorted(
        found.values(), key=lambda s: s.published or window_start, reverse=True
    )
    return tuple(newest_first[:MAX_SOURCES]), tuple(warnings)


def in_window(source: Source, window_start: date, window_end: date) -> bool:
    """Keep undated sources (the model is told their date is unknown)."""
    if source.published is None:
        return True
    return window_start <= source.published <= window_end


def draft(
    settings: Settings,
    request: MeetingRequest,
    sources: tuple[Source, ...],
    window_start: date,
    window_end: date,
) -> tuple[str, tuple[Development, ...], tuple[str, ...], LLMCall]:
    notes = f"Extra context from the user: {request.notes}\n" if request.notes else ""
    system = (
        DRAFT_SYSTEM.replace("{subject}", request.subject)
        .replace("{purpose}", request.purpose)
        .replace("{meeting_time}", request.meeting_time.strftime("%Y-%m-%d %H:%M"))
        .replace("{window_start}", window_start.isoformat())
        .replace("{window_end}", window_end.isoformat())
        .replace("{notes}", notes)
        .replace("{max_developments}", str(MAX_DEVELOPMENTS))
    )
    parsed, call = chat_json(
        settings.bifrost_url,
        settings.bifrost_virtual_key,
        settings.strong,
        system,
        format_sources(sources),
    )
    raw_items = parsed.get("developments")
    developments = tuple(
        item
        for item in (
            to_development(raw, len(sources))
            for raw in (raw_items if isinstance(raw_items, list) else [])
        )
        if item is not None
    )[:MAX_DEVELOPMENTS]
    raw_questions = parsed.get("open_questions")
    questions = tuple(
        str(q).strip()
        for q in (raw_questions if isinstance(raw_questions, list) else [])
        if str(q).strip()
    )[:MAX_OPEN_QUESTIONS]
    return str(parsed.get("summary") or "").strip(), developments, questions, call


def format_sources(sources: tuple[Source, ...]) -> str:
    blocks = []
    for number, source in enumerate(sources, start=1):
        published = source.published.isoformat() if source.published else "unknown"
        blocks.append(
            f"[{number}] {source.title} (published: {published})\n"
            f"URL: {source.url}\n{source.snippet}"
        )
    return "SOURCES:\n" + "\n\n".join(blocks)


def to_development(raw: object, source_count: int) -> Development | None:
    """Parse one drafted item. An item with no valid citation is dropped."""
    if not isinstance(raw, dict):
        return None
    headline = str(raw.get("headline") or "").strip()
    numbers = raw.get("sources")
    cited = tuple(
        n
        for n in (numbers if isinstance(numbers, list) else [])
        if isinstance(n, int) and 1 <= n <= source_count
    )
    if not headline or not cited:
        return None
    is_verified = str(raw.get("confidence") or "").strip().lower() == "verified"
    return Development(
        headline=headline,
        detail=str(raw.get("detail") or "").strip(),
        category=str(raw.get("category") or "other").strip().lower(),
        happened_on=str(raw.get("date") or "").strip(),
        source_numbers=cited,
        status=Status.VERIFIED if is_verified else Status.UNCERTAIN,
        status_reason=str(raw.get("reason") or "").strip(),
    )


def cross_check(
    settings: Settings,
    subject: str,
    item: Development,
    today: date,
    trusted_domains: tuple[str, ...] = (),
) -> tuple[Development, LLMCall | None, str | None]:
    """Re-verify one drafted item with the stale-answer detector."""
    statement = f"{item.headline}. {item.detail}".strip()
    claim = Claim(
        text=statement,
        category=item.category,
        search_query=f"{subject} {item.headline}",
    )
    result, call, warning = check_claim(settings, claim, today, trusted_domains)
    if warning is not None:
        # The check itself failed (search or model error). That says nothing
        # about the item, so keep the drafted status and report the failure.
        return item, call, f"Could not cross-check '{item.headline}': {warning}"
    verdict = result.verification.verdict
    explanation = result.verification.explanation
    if verdict in (Verdict.OUTDATED, Verdict.CONTRADICTED):
        checked = replace(
            item,
            status=Status.DISPUTED,
            status_reason=explanation or "A fresh search contradicts this.",
        )
    elif verdict is Verdict.UNVERIFIABLE and item.status is Status.VERIFIED:
        checked = replace(
            item,
            status=Status.UNCERTAIN,
            status_reason="A second, independent search could not confirm this.",
        )
    else:
        checked = item
    return replace(checked, freshness_score=result.freshness_score), call, warning


def check_talking_points(
    settings: Settings, request: MeetingRequest, today: date
) -> tuple[Report | None, tuple[str, ...]]:
    """Run the user's own talking points through the stale-answer detector."""
    if not request.talking_points.strip():
        return None, ()
    context = (
        f"These are talking points for a meeting with {request.subject}. "
        f"Prioritise claims about {request.subject} and name them in each search query."
    )
    try:
        report = analyze(
            settings,
            request.talking_points,
            today,
            request.trusted_domains,
            context,
        )
    except LLMError as exc:
        return None, (f"Could not check your talking points: {exc}",)
    return report, ()


def build_briefing(
    settings: Settings,
    request: MeetingRequest,
    today: date | None = None,
    verify: bool = True,
) -> Briefing:
    """Run the full pipeline for one meeting."""
    today = today or date.today()
    window_start, window_end = research_window(request.meeting_time.date(), today)
    sources, warnings = research(settings, request.subject, window_start, window_end)
    talking_points, talking_warnings = check_talking_points(settings, request, today)
    warnings += talking_warnings

    if not sources:
        return Briefing(
            request=request,
            window_start=window_start,
            window_end=window_end,
            summary="No dated coverage of this subject was found in the research window.",
            developments=(),
            open_questions=(),
            sources=(),
            calls=(),
            warnings=warnings,
            talking_points=talking_points,
        )

    summary, developments, questions, draft_call = draft(
        settings, request, sources, window_start, window_end
    )
    calls: tuple[LLMCall, ...] = (draft_call,)

    if verify and developments:
        with ThreadPoolExecutor(max_workers=PARALLEL_CHECKS) as pool:
            outcomes = list(
                pool.map(
                    lambda item: cross_check(
                        settings, request.subject, item, today, request.trusted_domains
                    ),
                    developments,
                )
            )
        developments = tuple(item for item, _, _ in outcomes)
        calls += tuple(call for _, call, _ in outcomes if call)
        warnings += tuple(warning for _, _, warning in outcomes if warning)

    return Briefing(
        request=request,
        window_start=window_start,
        window_end=window_end,
        summary=summary,
        developments=developments,
        open_questions=questions,
        sources=sources,
        calls=calls,
        warnings=warnings,
        talking_points=talking_points,
    )
