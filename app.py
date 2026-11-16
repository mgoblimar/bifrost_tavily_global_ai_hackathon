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

st.markdown(
    """
**How it works**

1. A fast model, called through the **Bifrost** gateway, pulls the time-sensitive
   claims out of the answer.
2. **Tavily** searches the live web for each claim.
3. A stronger model, again through Bifrost, judges each claim using only those sources.
4. Each claim gets a 0-100 freshness score computed in plain code.

If a model provider is down or rate-limited, Bifrost falls back to the other
provider automatically, and the app shows which one answered.
"""
)
