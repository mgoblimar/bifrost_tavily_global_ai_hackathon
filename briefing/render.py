"""Render a briefing as a one-page Markdown document."""

from briefing.models import Briefing, Development, Status

STATUS_LABEL = {
    Status.VERIFIED: "Verified",
    Status.UNCERTAIN: "Uncertain",
    Status.DISPUTED: "Disputed",
}


def to_markdown(briefing: Briefing) -> str:
    request = briefing.request
    lines = [
        f"# Briefing: {request.subject}",
        "",
        f"**Meeting:** {request.meeting_time.strftime('%A, %d %B %Y, %H:%M')}  ",
        f"**Purpose:** {request.purpose}  ",
        f"**Research window:** {briefing.window_start.isoformat()} to "
        f"{briefing.window_end.isoformat()}",
        "",
        "## At a glance",
        "",
        briefing.summary,
        "",
    ]
    confirmed = [d for d in briefing.developments if d.status is Status.VERIFIED]
    other = [d for d in briefing.developments if d.status is not Status.VERIFIED]
    lines += _section("Verified developments", confirmed)
    lines += _section("Uncertain or disputed: check before relying on these", other)

    if briefing.open_questions:
        lines += ["## Open questions for the meeting", ""]
        lines += [f"- {question}" for question in briefing.open_questions]
        lines.append("")

    if briefing.sources:
        lines += ["## Sources", ""]
        for number, source in enumerate(briefing.sources, start=1):
            published = source.published.isoformat() if source.published else "no date"
            lines.append(f"{number}. [{source.title}]({source.url}) ({published})")
        lines.append("")
    return "\n".join(lines)


def _section(title: str, items: list[Development]) -> list[str]:
    if not items:
        return []
    lines = [f"## {title}", ""]
    for item in items:
        cites = "".join(f"[{n}]" for n in item.source_numbers)
        when = f" ({item.happened_on})" if item.happened_on else ""
        label = STATUS_LABEL[item.status]
        lines.append(f"- **{item.headline}**{when} {cites}  ")
        lines.append(f"  {item.detail}  ")
        lines.append(f"  _{label}: {item.status_reason}_")
    lines.append("")
    return lines
