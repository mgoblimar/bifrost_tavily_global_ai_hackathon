"""Stale-Answer Detector page."""

import streamlit as st

from core.config import ConfigError, load_settings
from core.llm import LLMError
from stale_detector.models import Report, Verdict
from stale_detector.pipeline import MAX_CLAIMS, analyze
from stale_detector.view import render_claim, render_gateway, trusted_sites_input

SAMPLE_ANSWER = (
    "ChatGPT Plus costs $20 per month and gives you access to GPT-4, OpenAI's most "
    "capable model. Twitter's CEO is Linda Yaccarino. The latest stable Python "
    "release is 3.12, and Node.js 18 is the current LTS version. Next.js 13 "
    "introduced the App Router, which is the newest way to build Next.js apps."
)

st.set_page_config(page_title="Stale-Answer Detector", page_icon="🕒", layout="wide")


def render_report(report: Report) -> None:
    if not report.results:
        st.success("No time-sensitive claims found in this answer.")
        render_gateway(report.calls, "Extract claims", "Verify claim")
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

    render_gateway(report.calls, "Extract claims", "Verify claim")


st.title("Stale-Answer Detector")
st.caption(
    "Paste an AI-generated answer. Each time-sensitive claim is re-checked against "
    f"the live web and given a freshness score. Up to {MAX_CLAIMS} claims per run."
)

answer = st.text_area("AI-generated answer", value=SAMPLE_ANSWER, height=180)
trusted_domains = trusted_sites_input("detector")

if st.button("Check freshness", type="primary"):
    if not answer.strip():
        st.error("Paste an answer to check first.")
        st.stop()
    try:
        settings = load_settings()
        with st.spinner("Extracting claims and checking live sources..."):
            st.session_state["stale_report"] = analyze(
                settings, answer, trusted_domains=trusted_domains
            )
    except (ConfigError, LLMError) as exc:
        st.error(str(exc))
        st.stop()

if "stale_report" in st.session_state:
    render_report(st.session_state["stale_report"])
