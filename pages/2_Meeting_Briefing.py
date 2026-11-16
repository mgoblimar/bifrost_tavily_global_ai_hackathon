"""Pre-Meeting Briefing page."""

from datetime import date, datetime, time, timedelta

import streamlit as st

from briefing.models import Briefing, Development, MeetingRequest, Status
from briefing.pipeline import WINDOW_DAYS, build_briefing
from briefing.render import to_markdown
from core.config import ConfigError, load_settings
from core.llm import LLMError

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


def render_gateway(briefing: Briefing) -> None:
    if not briefing.calls:
        return
    with st.expander("Gateway activity (Bifrost)"):
        tokens = sum(c.prompt_tokens + c.completion_tokens for c in briefing.calls)
        fallbacks = sum(1 for c in briefing.calls if c.is_fallback)
        col_calls, col_tokens, col_fallbacks = st.columns(3)
        col_calls.metric("Model calls", len(briefing.calls))
        col_tokens.metric("Total tokens", f"{tokens:,}")
        col_fallbacks.metric("Fallbacks used", fallbacks)
        st.dataframe(
            [
                {
                    "Step": "Draft briefing" if index == 0 else "Cross-check item",
                    "Requested": call.requested_model,
                    "Served by": call.served_by,
                    "Fallback": "yes" if call.is_fallback else "no",
                }
                for index, call in enumerate(briefing.calls)
            ],
            hide_index=True,
            use_container_width=True,
        )


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
    render_gateway(briefing)


st.title("Pre-Meeting Briefing")
st.caption(
    f"Enter who you are meeting and when. You get a one-page briefing on the last "
    f"{WINDOW_DAYS} days, with every item sourced and cross-checked against a fresh search."
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
