"""Pre-Meeting Briefing page."""

from datetime import date, datetime, time, timedelta

import streamlit as st

from briefing.models import Briefing, Development, MeetingRequest, Status
from briefing.pipeline import WINDOW_DAYS, build_briefing
from briefing.render import to_markdown
from core.config import ConfigError, load_settings
from core.llm import LLMError
from stale_detector.models import Verdict
from stale_detector.view import render_claim, render_gateway, trusted_sites_input

PURPOSES = (
    "Sales call",
    "Partnership discussion",
    "Investor meeting",
    "Job interview",
    "Pharma rep visit to a hospital or distributor",
    "Other",
)
STATUS_STYLE = {
    Status.VERIFIED: ("Verified", "green"),
    Status.UNCERTAIN: ("Uncertain", "orange"),
    Status.DISPUTED: ("Disputed", "red"),
}

st.set_page_config(page_title="Meeting Briefing", page_icon="📋", layout="wide")


def render_development(item: Development, briefing: Briefing) -> None:
    label, color = STATUS_STYLE[item.status]
    with st.container(border=True):
        text_col, score_col = st.columns([5, 1])
        with text_col:
            st.badge(label, color=color)
            when = f" · {item.happened_on}" if item.happened_on else ""
            st.markdown(f"**{item.headline}**")
            st.caption(f"{item.category}{when}")
        if item.freshness_score is not None:
            score_col.metric("Freshness", f"{item.freshness_score}/100")
        st.write(item.detail)
        if item.status_reason:
            st.caption(f"{label}: {item.status_reason}")
        for number in item.source_numbers:
            source = briefing.sources[number - 1]
            published = source.published.isoformat() if source.published else "no date"
            st.markdown(f"[{number}] [{source.title}]({source.url}) · {published}")


def render_talking_points(briefing: Briefing) -> None:
    report = briefing.talking_points
    if report is None:
        return
    st.markdown("#### Your talking points, checked")
    if not report.results:
        st.success("No time-sensitive claims were found in your talking points.")
        return
    stale = sum(
        1
        for r in report.results
        if r.verification.verdict in (Verdict.OUTDATED, Verdict.CONTRADICTED)
    )
    if stale:
        st.error(f"{stale} of your talking points are out of date. Fix them before the meeting.")
    else:
        st.success("Nothing in your talking points was found to be out of date.")
    for warning in report.warnings:
        st.warning(warning)
    for result in sorted(report.results, key=lambda r: r.freshness_score):
        render_claim(result)


def render_briefing(briefing: Briefing) -> None:
    request = briefing.request
    st.subheader(f"Briefing: {request.subject}")
    st.caption(
        f"{request.meeting_time.strftime('%A, %d %B %Y, %H:%M')} · {request.purpose} · "
        f"research window {briefing.window_start.isoformat()} to "
        f"{briefing.window_end.isoformat()}"
    )
    for warning in briefing.warnings:
        st.warning(warning)

    st.markdown("#### At a glance")
    st.write(briefing.summary)

    confirmed = [d for d in briefing.developments if d.status is Status.VERIFIED]
    other = [d for d in briefing.developments if d.status is not Status.VERIFIED]
    if confirmed:
        st.markdown("#### Verified developments")
        for item in confirmed:
            render_development(item, briefing)
    if other:
        st.markdown("#### Uncertain or disputed")
        st.caption("Check these before relying on them in the meeting.")
        for item in other:
            render_development(item, briefing)

    render_talking_points(briefing)

    if briefing.open_questions:
        st.markdown("#### Open questions for the meeting")
        for question in briefing.open_questions:
            st.markdown(f"- {question}")

    if briefing.sources:
        with st.expander(f"All sources ({len(briefing.sources)})"):
            for number, source in enumerate(briefing.sources, start=1):
                published = (
                    source.published.isoformat() if source.published else "no date"
                )
                st.markdown(f"{number}. [{source.title}]({source.url}) · {published}")

    st.download_button(
        "Download one-page briefing (Markdown)",
        data=to_markdown(briefing),
        file_name=f"briefing-{request.subject.lower().replace(' ', '-')}.md",
        mime="text/markdown",
    )
    calls = briefing.calls + (briefing.talking_points.calls if briefing.talking_points else ())
    render_gateway(calls, "Draft briefing", "Cross-check")


st.title("Pre-Meeting Briefing")
st.caption(
    f"Enter who you are meeting and when. You get a one-page briefing on the last "
    f"{WINDOW_DAYS} days, with every item sourced and cross-checked. Paste your talking "
    "points to have them checked too."
)

with st.form("briefing_form"):
    subject = st.text_input("Company or person", placeholder="e.g. Nvidia")
    col_date, col_time, col_purpose = st.columns([1, 1, 2])
    meeting_date = col_date.date_input("Meeting date", value=date.today() + timedelta(days=1))
    meeting_clock = col_time.time_input("Meeting time", value=time(10, 0))
    purpose = col_purpose.selectbox("Meeting purpose", PURPOSES)
    notes = st.text_input(
        "Anything specific to focus on? (optional)",
        placeholder="e.g. their data-centre products, or which Nvidia if the name is ambiguous",
    )
    talking_points = st.text_area(
        "Your talking points (optional)",
        placeholder="Paste what you or an AI chatbot drafted for this meeting. "
        "Anything that is no longer true will be flagged.",
        height=120,
    )
    trusted_domains = trusted_sites_input("briefing")
    verify = st.checkbox("Cross-check each item with a second search (slower)", value=True)
    submitted = st.form_submit_button("Build briefing", type="primary")

if submitted:
    if not subject.strip():
        st.error("Enter a company or person first.")
        st.stop()
    request = MeetingRequest(
        subject=subject.strip(),
        meeting_time=datetime.combine(meeting_date, meeting_clock),
        purpose=purpose,
        notes=notes.strip(),
        talking_points=talking_points.strip(),
        trusted_domains=trusted_domains,
    )
    try:
        settings = load_settings()
        with st.spinner("Researching, drafting and cross-checking..."):
            st.session_state["briefing"] = build_briefing(settings, request, verify=verify)
    except (ConfigError, LLMError) as exc:
        st.error(str(exc))
        st.stop()

if "briefing" in st.session_state:
    render_briefing(st.session_state["briefing"])
