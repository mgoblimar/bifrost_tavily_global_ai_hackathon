"""Mini evaluation: run hand-labelled claims through the detector and score it.

Usage (Bifrost must be running):  python -m eval.run_eval

Each claim is labelled "stale" or "fresh" by hand. The detector predicts
"stale" for an outdated/contradicted verdict, "fresh" for a current verdict,
and abstains on unverifiable. Results are written to eval/results.md.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from core.config import Settings, load_settings
from core.llm import LLMError
from stale_detector.models import Verdict
from stale_detector.pipeline import check_claim, extract_claims

EVAL_DIR = Path(__file__).parent
PARALLEL = 2
STALE_VERDICTS = (Verdict.OUTDATED, Verdict.CONTRADICTED)


@dataclass(frozen=True)
class Outcome:
    claim: str
    label: str
    predicted: str  # "stale", "fresh" or "abstain"
    score: int | None
    note: str


def predict(settings: Settings, item: dict, today: date) -> Outcome:
    try:
        claims, _ = extract_claims(settings, item["claim"], today)
    except LLMError as exc:
        return Outcome(item["claim"], item["label"], "abstain", None, f"error: {exc}")
    if not claims:
        return Outcome(item["claim"], item["label"], "abstain", None, "not extracted")

    result, _, warning = check_claim(settings, claims[0], today)
    verdict = result.verification.verdict
    if verdict in STALE_VERDICTS:
        predicted = "stale"
    elif verdict is Verdict.CURRENT:
        predicted = "fresh"
    else:
        predicted = "abstain"
    note = warning or result.verification.current_value or result.verification.explanation
    return Outcome(item["claim"], item["label"], predicted, result.freshness_score, note)


def summarise(outcomes: list[Outcome]) -> dict:
    answered = [o for o in outcomes if o.predicted != "abstain"]
    correct = [o for o in answered if o.predicted == o.label]
    true_stale = [o for o in outcomes if o.label == "stale"]
    flagged = [o for o in outcomes if o.predicted == "stale"]
    caught = [o for o in flagged if o.label == "stale"]
    return {
        "total": len(outcomes),
        "answered": len(answered),
        "abstained": len(outcomes) - len(answered),
        "correct": len(correct),
        "accuracy_when_answered": len(correct) / len(answered) if answered else 0.0,
        "stale_precision": len(caught) / len(flagged) if flagged else 0.0,
        "stale_recall": len(caught) / len(true_stale) if true_stale else 0.0,
    }


def to_markdown(outcomes: list[Outcome], summary: dict, today: date) -> str:
    lines = [
        f"# Mini eval results ({today.isoformat()})",
        "",
        f"- Claims: {summary['total']} ({summary['abstained']} abstained as unverifiable)",
        f"- Accuracy when it gave a verdict: {summary['accuracy_when_answered']:.0%} "
        f"({summary['correct']}/{summary['answered']})",
        f"- Stale-claim precision: {summary['stale_precision']:.0%}",
        f"- Stale-claim recall: {summary['stale_recall']:.0%}",
        "",
        "| Claim | Label | Predicted | Score | Now / note |",
        "|---|---|---|---|---|",
    ]
    for o in outcomes:
        mark = "" if o.predicted in (o.label, "abstain") else " ❌"
        note = o.note.replace("|", "/").replace("\n", " ")[:120]
        score = "" if o.score is None else str(o.score)
        lines.append(f"| {o.claim} | {o.label} | {o.predicted}{mark} | {score} | {note} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    settings = load_settings()
    today = date.today()
    items = json.loads((EVAL_DIR / "claims.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        outcomes = list(pool.map(lambda item: predict(settings, item, today), items))
    summary = summarise(outcomes)
    report = to_markdown(outcomes, summary, today)
    (EVAL_DIR / "results.md").write_text(report, encoding="utf-8")
    print(report)  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
