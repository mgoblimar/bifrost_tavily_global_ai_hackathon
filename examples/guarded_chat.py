"""Example AI application: a chat assistant with a freshness check behind it.

It shows the pattern for adding Carbon Date to an existing AI feature:

    1. Your app asks a model a question, as it does today.
    2. Before showing the answer, it sends the answer to POST /v1/verify.
    3. It shows the answer with any stale claims flagged and corrected.

Run (Bifrost and the verification API must be running):

    python -m examples.guarded_chat "What is the latest stable version of Python?"
"""

import sys

import requests

from core.config import load_settings
from core.llm import chat_text

VERIFY_URL = "http://localhost:8600/v1/verify"
VERIFY_TIMEOUT_SECONDS = 180
ASSISTANT_SYSTEM = "You are a helpful assistant. Answer in three or four sentences."


def ask_model(question: str) -> str:
    """Step 1: the app's normal model call, through Bifrost."""
    settings = load_settings()
    answer, _ = chat_text(
        settings.bifrost_url,
        settings.bifrost_virtual_key,
        settings.fast,
        ASSISTANT_SYSTEM,
        question,
    )
    return answer.strip()


def verify(answer: str) -> dict:
    """Step 2: one HTTP call to the verification layer."""
    response = requests.post(
        VERIFY_URL, json={"answer": answer}, timeout=VERIFY_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.json()


def format_reply(answer: str, report: dict) -> str:
    """Step 3: show the answer with stale claims called out."""
    lines = ["ASSISTANT:", answer, ""]
    stale = [claim for claim in report["claims"] if claim["is_stale"]]
    if not report["claims"]:
        lines.append("FRESHNESS CHECK: no time-sensitive claims in this answer.")
    elif not stale:
        lines.append(
            f"FRESHNESS CHECK: {report['claims_checked']} claims checked, none out of date."
        )
    else:
        lines.append(
            f"FRESHNESS CHECK: {len(stale)} of {report['claims_checked']} claims "
            "are out of date."
        )
        for claim in stale:
            lines.append(f"  - Said: {claim['claim']}")
            if claim["current_value"]:
                lines.append(f"    Now:  {claim['current_value']}")
            used = [s["url"] for s in claim["sources"] if s["used_for_verdict"]]
            if used:
                lines.append(f"    Source: {used[0]}")
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('Usage: python -m examples.guarded_chat "your question"')
    question = " ".join(sys.argv[1:])
    answer = ask_model(question)
    reply = format_reply(answer, verify(answer))
    # Models often emit non-breaking hyphens, which many console fonts cannot draw.
    sys.stdout.write(reply.replace("‑", "-") + "\n")


if __name__ == "__main__":
    main()
