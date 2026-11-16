"""Home page. Run with: streamlit run app.py"""

import streamlit as st

st.set_page_config(page_title="Fresh Facts", page_icon="🧭", layout="wide")

st.title("Fresh Facts")
st.caption("Live-web verification tools built on Tavily and Bifrost.")

st.page_link(
    "pages/1_Stale_Answer_Detector.py",
    label="Stale-Answer Detector",
    icon="🕒",
    help="Paste an AI-generated answer and see which claims have gone out of date.",
)
st.page_link(
    "pages/2_Meeting_Briefing.py",
    label="Pre-Meeting Briefing",
    icon="📋",
    help="A one-page, sourced briefing on a company or person before a meeting.",
)

st.markdown(
    """
**Stale-Answer Detector**

1. A fast model, called through the **Bifrost** gateway, pulls the time-sensitive
   claims out of the answer.
2. **Tavily** searches the live web for each claim, including dated news.
3. A stronger model, again through Bifrost, judges each claim using only those sources.
4. Each claim gets a 0-100 freshness score computed in plain code.

**Pre-Meeting Briefing**

1. **Tavily** collects dated news about the company or person from the last 30 days.
2. A model drafts a one-page briefing where every item cites its sources.
3. Each item is then re-checked by the stale-answer detector, so the briefing
   separates verified developments from uncertain or disputed ones.

If a model provider is down or rate-limited, Bifrost falls back to the other
provider automatically, and the app shows which one answered.
"""
)
