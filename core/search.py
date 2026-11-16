"""Live web search through Tavily."""

from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime

from tavily import TavilyClient

SNIPPET_MAX_CHARS = 600


class SearchError(RuntimeError):
    """Raised when Tavily cannot complete a search."""


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    snippet: str
    published: date | None


def search_web(
    api_key: str,
    query: str,
    max_results: int = 5,
    days: int | None = None,
) -> tuple[Source, ...]:
    """Search the live web. Pass `days` to restrict to recent news only."""
    options: dict = {
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
    }
    if days is not None:
        options["topic"] = "news"
        options["days"] = days

    try:
        response = TavilyClient(api_key=api_key).search(**options)
    except Exception as exc:  # the SDK raises several unrelated error types
        raise SearchError(f"Tavily search failed for '{query}': {exc}") from exc

    results = response.get("results") or []
    return tuple(_to_source(item) for item in results if item.get("url"))


def _to_source(item: dict) -> Source:
    return Source(
        title=(item.get("title") or item["url"]).strip(),
        url=item["url"],
        snippet=(item.get("content") or "").strip()[:SNIPPET_MAX_CHARS],
        published=parse_published(item.get("published_date")),
    )


def parse_published(raw: str | None) -> date | None:
    """Tavily dates arrive as RFC 2822 or ISO 8601; return None if unreadable."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None
