"""Stale-Answer Detector page."""

import streamlit as st

from core.config import ConfigError, load_settings
from core.llm import LLMError
from stale_detector.models import ClaimResult, Report, Verdict
from stale_detector.pipeline import MAX_CLAIMS, analyze

SAMPLE_ANSWER = (
    "ChatGPT Plus costs $20 per month and gives you access to GPT-4, OpenAI's most "
    "capable model. Twitter's CEO is Linda Yaccarino. The latest stable Python "
    "release is 3.12, and Node.js 18 is the current LTS version. Next.js 13 "
    "introduced the App Router, which is the newest way to build Next.js apps."
)

VERDICT_STYLE = {
    Verdict.CURRENT: ("Current", "green"),
    Verdict.OUTDATED: ("Outdated", "orange"),
    Verdict.CONTRADICTED: ("Contradicted", "red"),
    Verdict.UNVERIFIABLE: ("Unverifiable", "gray"),
}

st.set_page_config(page_title="Stale-Answer Detector", page_icon="🕒", layout="wide")


def render_claim(result: ClaimResult) -> None:
    label, color = VERDICT_STYLE[result.verification.verdict]
    with st.container(border=True):
        text_col, score_col = st.columns([5, 1])
        with text_col:
            st.badge(label, color=color)
            st.markdown(f"**{result.claim.text}**")
            st.caption(f"Category: {result.claim.category}")
        score_col.metric("Freshness", f"{result.freshness_score}/100")

        if result.verification.explanation:
            st.write(result.verification.explanation)
        if result.verification.current_value:
            st.info(f"Now: {result.verification.current_value}")

        if result.sources:
            with st.expander(f"Sources ({len(result.sources)})"):
                for number, source in enumerate(result.sources, start=1):
                    used = source.url in result.verification.supporting_urls
                    date_text = (
                        source.published.isoformat() if source.published else "no date"
                    )
                    marker = " · used for verdict" if used else ""
                    st.markdown(f"[{number}] [{source.title}]({source.url})")
                    st.caption(f"{date_text}{marker}")


def render_gateway(report: Report) -> None:
    st.subheader("Gateway activity (Bifrost)")
    fallbacks = sum(1 for call in report.calls if call.is_fallback)
    tokens = sum(c.prompt_tokens + c.completion_tokens for c in report.calls)
    col_calls, col_tokens, col_fallbacks = st.columns(3)
    col_calls.metric("Model calls", len(report.calls))
    col_tokens.metric("Total tokens", f"{tokens:,}")
    col_fallbacks.metric("Fallbacks used", fallbacks)
    st.dataframe(
        [
            {
                "Step": "Extract claims" if index == 0 else "Verify claim",
                "Requested": call.requested_model,
                "Served by": call.served_by,
                "Fallback": "yes" if call.is_fallback else "no",
                "Tokens in": call.prompt_tokens,
                "Tokens out": call.completion_tokens,
            }
            for index, call in enumerate(report.calls)
        ],
        hide_index=True,
        use_container_width=True,
    )


def render_report(report: Report) -> None:
    if not report.results:
        st.success("No time-sensitive claims found in this answer.")
        render_gateway(report)
        return

    stale = sum(
        1
        for r in report.results
        if r.verification.verdict in (Verdict.OUTDATED, Verdict.CONTRADICTED)
    )
    col_score, col_checked, col_stale = st.columns(3)
    col_score.metric("Overall freshness", f"{report.overall_score}/100")
    col_checked.metric("Claims checked", len(report.results))
    col_stale.metric("Stale or wrong", stale)

    for warning in report.warnings:
        st.warning(warning)

    for result in sorted(report.results, key=lambda r: r.freshness_score):
        render_claim(result)

    render_gateway(report)


st.title("Stale-Answer Detector")
st.caption(
    "Paste an AI-generated answer. Each time-sensitive claim is re-checked against "
    f"the live web and given a freshness score. Up to {MAX_CLAIMS} claims per run."
)

answer = st.text_area("AI-generated answer", value=SAMPLE_ANSWER, height=180)

if st.button("Check freshness", type="primary"):
    if not answer.strip():
        st.error("Paste an answer to check first.")
        st.stop()
    try:
        settings = load_settings()
        with st.spinner("Extracting claims and checking live sources..."):
            st.session_state["stale_report"] = analyze(settings, answer)
    except (ConfigError, LLMError) as exc:
        st.error(str(exc))
        st.stop()

if "stale_report" in st.session_state:
    render_report(st.session_state["stale_report"])
