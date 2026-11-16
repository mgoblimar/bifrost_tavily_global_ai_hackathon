"""Streamlit pieces shared by both pages."""

import streamlit as st

from core.llm import LLMCall
from core.trusted import PRESETS, parse_domains
from stale_detector.models import ClaimResult, Verdict, evidence_basis

VERDICT_STYLE = {
    Verdict.CURRENT: ("Current", "green"),
    Verdict.OUTDATED: ("Outdated", "orange"),
    Verdict.CONTRADICTED: ("Contradicted", "red"),
    Verdict.UNVERIFIABLE: ("Unverifiable", "gray"),
}


def trusted_sites_input(key: str) -> tuple[str, ...]:
    """Preset plus free-text input for official sites; returns clean domains."""
    col_preset, col_custom = st.columns([1, 2])
    preset = col_preset.selectbox(
        "Official sources to check first", list(PRESETS), key=f"{key}_preset"
    )
    custom = col_custom.text_input(
        "Other trusted sites (optional, comma-separated)",
        placeholder="e.g. the company's own site: nvidia.com",
        key=f"{key}_custom",
    )
    return parse_domains(", ".join(PRESETS[preset]) + ", " + custom)


def render_claim(result: ClaimResult) -> None:
    label, color = VERDICT_STYLE[result.verification.verdict]
    with st.container(border=True):
        text_col, score_col = st.columns([5, 1])
        with text_col:
            st.badge(label, color=color)
            st.markdown(f"**{result.claim.text}**")
            st.caption(
                f"Category: {result.claim.category} · Based on: {evidence_basis(result)}"
            )
        score_col.metric("Freshness", f"{result.freshness_score}/100")

        if result.verification.explanation:
            st.write(result.verification.explanation)
        if result.verification.current_value:
            st.info(f"Now: {result.verification.current_value}")

        if result.sources:
            with st.expander(f"Sources ({len(result.sources)})"):
                for number, source in enumerate(result.sources, start=1):
                    notes = [source.published.isoformat() if source.published else "no date"]
                    if source.official:
                        notes.append("official source")
                    if source.url in result.verification.supporting_urls:
                        notes.append("used for verdict")
                    st.markdown(f"[{number}] [{source.title}]({source.url})")
                    st.caption(" · ".join(notes))


def render_gateway(calls: tuple[LLMCall, ...], first_step: str, other_steps: str) -> None:
    """Show what the Bifrost gateway did for this run."""
    if not calls:
        return
    with st.expander("Gateway activity (Bifrost)"):
        tokens = sum(c.prompt_tokens + c.completion_tokens for c in calls)
        fallbacks = sum(1 for c in calls if c.is_fallback)
        col_calls, col_tokens, col_fallbacks = st.columns(3)
        col_calls.metric("Model calls", len(calls))
        col_tokens.metric("Total tokens", f"{tokens:,}")
        col_fallbacks.metric("Fallbacks used", fallbacks)
        st.dataframe(
            [
                {
                    "Step": first_step if index == 0 else other_steps,
                    "Requested": call.requested_model,
                    "Served by": call.served_by,
                    "Fallback": "yes" if call.is_fallback else "no",
                    "Tokens in": call.prompt_tokens,
                    "Tokens out": call.completion_tokens,
                }
                for index, call in enumerate(calls)
            ],
            hide_index=True,
            use_container_width=True,
        )
