"""Stale-answer detection: extract claims -> search live -> verify -> score."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

from core.config import Settings
from core.llm import LLMCall, LLMError, chat_json
from core.search import SearchError, Source, search_web
from core.trusted import is_trusted
from stale_detector.models import Claim, ClaimResult, Report, Verdict, Verification
from stale_detector.prompts import EXTRACT_SYSTEM, VERIFY_SYSTEM
from stale_detector.scoring import freshness_score, overall_score

MAX_CLAIMS = 6
MAX_ANSWER_CHARS = 8000
SOURCES_PER_CLAIM = 5
NEWS_SOURCES_PER_CLAIM = 4
NEWS_WINDOW_DAYS = 365
OFFICIAL_SOURCES_PER_CLAIM = 3
PARALLEL_CLAIMS = 3


def extract_claims(
    settings: Settings, answer: str, today: date, context: str = ""
) -> tuple[tuple[Claim, ...], LLMCall]:
    """Step 1 (fast model): pull out the time-sensitive claims."""
    system = (
        EXTRACT_SYSTEM.replace("{max_claims}", str(MAX_CLAIMS))
        .replace("{today}", today.isoformat())
        .replace("{year}", str(today.year))
        .replace("{context}", f"Context: {context}\n" if context else "")
    )
    parsed, call = chat_json(
        settings.bifrost_url,
        settings.bifrost_virtual_key,
        settings.fast,
        system,
        answer[:MAX_ANSWER_CHARS],
    )
    raw_claims = parsed.get("claims")
    if not isinstance(raw_claims, list):
        raise LLMError("Claim extraction did not return a list of claims.")
    claims = tuple(
        claim for claim in map(_to_claim, raw_claims[:MAX_CLAIMS]) if claim is not None
    )
    return claims, call


def _to_claim(raw: object) -> Claim | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    return Claim(
        text=text,
        category=str(raw.get("category") or "other").strip().lower(),
        search_query=str(raw.get("search_query") or text).strip(),
    )


def verify_claim(
    settings: Settings, claim: Claim, sources: tuple[Source, ...], today: date
) -> tuple[Verification, LLMCall]:
    """Step 3 (strong model): judge the claim using only the live sources."""
    system = VERIFY_SYSTEM.replace("{today}", today.isoformat())
    user = f"CLAIM: {claim.text}\n\nSOURCES:\n{_format_sources(sources)}"
    parsed, call = chat_json(
        settings.bifrost_url, settings.bifrost_virtual_key, settings.strong, system, user
    )
    return _to_verification(parsed, sources), call


def _format_sources(sources: tuple[Source, ...]) -> str:
    lines = []
    for number, source in enumerate(sources, start=1):
        published = source.published.isoformat() if source.published else "unknown"
        official = " [OFFICIAL SOURCE]" if source.official else ""
        lines.append(
            f"[{number}]{official} {source.title} (published: {published})\n"
            f"URL: {source.url}\n{source.snippet}"
        )
    return "\n\n".join(lines)


def _to_verification(parsed: dict, sources: tuple[Source, ...]) -> Verification:
    try:
        verdict = Verdict(str(parsed.get("verdict") or "").strip().lower())
    except ValueError:
        verdict = Verdict.UNVERIFIABLE
    try:
        confidence = float(parsed.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.5

    numbers = parsed.get("supporting_sources")
    urls = tuple(
        sources[n - 1].url
        for n in (numbers if isinstance(numbers, list) else [])
        if isinstance(n, int) and 1 <= n <= len(sources)
    )
    return Verification(
        verdict=verdict,
        confidence=min(max(confidence, 0.0), 1.0),
        explanation=str(parsed.get("explanation") or "").strip(),
        current_value=str(parsed.get("current_value") or "").strip(),
        supporting_urls=urls,
    )


def gather_sources(
    settings: Settings, claim: Claim, trusted_domains: tuple[str, ...] = ()
) -> tuple[Source, ...]:
    """Step 2: official sites first, then general web results and dated news.

    General results are the most relevant but carry no publish date, so on their
    own the verifier cannot tell an old article from a new one. The news search
    adds dated evidence. When the user names trusted sites, those are searched
    too and listed first. Both extra searches are best-effort: if one fails we
    keep the general results.
    """
    general = search_web(
        settings.tavily_api_key, claim.search_query, SOURCES_PER_CLAIM
    )
    try:
        news = search_web(
            settings.tavily_api_key,
            claim.search_query,
            NEWS_SOURCES_PER_CLAIM,
            days=NEWS_WINDOW_DAYS,
            depth="basic",
        )
    except SearchError:
        news = ()
    official: tuple[Source, ...] = ()
    if trusted_domains:
        try:
            official = search_web(
                settings.tavily_api_key,
                claim.search_query,
                OFFICIAL_SOURCES_PER_CLAIM,
                depth="basic",
                include_domains=trusted_domains,
            )
        except SearchError:
            official = ()

    merged: dict[str, Source] = {}
    for source in official + general + news:
        merged.setdefault(source.url, source)
    return tuple(
        replace(source, official=is_trusted(source.url, trusted_domains))
        for source in merged.values()
    )


def check_claim(
    settings: Settings,
    claim: Claim,
    today: date,
    trusted_domains: tuple[str, ...] = (),
) -> tuple[ClaimResult, LLMCall | None, str | None]:
    """Steps 2-4 for one claim. A failure degrades to 'unverifiable', never a crash."""
    try:
        sources = gather_sources(settings, claim, trusted_domains)
    except SearchError as exc:
        return _unverifiable(claim, (), "Live search failed."), None, str(exc)

    if not sources:
        return _unverifiable(claim, (), "No live sources were found."), None, None

    try:
        verification, call = verify_claim(settings, claim, sources, today)
    except LLMError as exc:
        return _unverifiable(claim, sources, "Verification failed."), None, str(exc)

    supporting = tuple(s for s in sources if s.url in verification.supporting_urls)
    score = freshness_score(
        verification.verdict, verification.confidence, supporting, today
    )
    return ClaimResult(claim, verification, sources, score), call, None


def _unverifiable(
    claim: Claim, sources: tuple[Source, ...], reason: str
) -> ClaimResult:
    verification = Verification(Verdict.UNVERIFIABLE, 0.0, reason, "", ())
    score = freshness_score(Verdict.UNVERIFIABLE, 0.0, (), date.today())
    return ClaimResult(claim, verification, sources, score)


def analyze(
    settings: Settings,
    answer: str,
    today: date | None = None,
    trusted_domains: tuple[str, ...] = (),
    context: str = "",
) -> Report:
    """Run the full pipeline on one piece of text.

    `trusted_domains` are official sites to search first. `context` tells the
    extractor what the text is for, such as talking points for a meeting.
    """
    today = today or date.today()
    claims, extract_call = extract_claims(settings, answer, today, context)

    with ThreadPoolExecutor(max_workers=PARALLEL_CLAIMS) as pool:
        outcomes = list(
            pool.map(lambda c: check_claim(settings, c, today, trusted_domains), claims)
        )

    results = tuple(result for result, _, _ in outcomes)
    calls = (extract_call,) + tuple(call for _, call, _ in outcomes if call)
    warnings = tuple(warning for _, _, warning in outcomes if warning)
    return Report(
        results=results,
        overall_score=overall_score(tuple(r.freshness_score for r in results)),
        calls=calls,
        warnings=warnings,
    )
