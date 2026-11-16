"""Turn a detector report into plain JSON-ready data for the API."""

from core.llm import LLMCall
from core.search import Source
from stale_detector.models import ClaimResult, Report, Verdict, evidence_basis

STALE_VERDICTS = (Verdict.OUTDATED, Verdict.CONTRADICTED)


def report_to_dict(report: Report) -> dict:
    stale = sum(1 for r in report.results if r.verification.verdict in STALE_VERDICTS)
    return {
        "overall_freshness": report.overall_score,
        "claims_checked": len(report.results),
        "stale_claims": stale,
        "claims": [_claim_to_dict(result) for result in report.results],
        "gateway": [_call_to_dict(call) for call in report.calls],
        "warnings": list(report.warnings),
    }


def _claim_to_dict(result: ClaimResult) -> dict:
    verification = result.verification
    return {
        "claim": result.claim.text,
        "category": result.claim.category,
        "verdict": verification.verdict.value,
        "is_stale": verification.verdict in STALE_VERDICTS,
        "freshness_score": result.freshness_score,
        "confidence": verification.confidence,
        "current_value": verification.current_value,
        "explanation": verification.explanation,
        "evidence_basis": evidence_basis(result),
        "sources": [
            _source_to_dict(source, source.url in verification.supporting_urls)
            for source in result.sources
        ],
    }


def _source_to_dict(source: Source, used: bool) -> dict:
    return {
        "title": source.title,
        "url": source.url,
        "published": source.published.isoformat() if source.published else None,
        "official": source.official,
        "used_for_verdict": used,
    }


def _call_to_dict(call: LLMCall) -> dict:
    return {
        "requested_model": call.requested_model,
        "served_by": call.served_by,
        "is_fallback": call.is_fallback,
        "prompt_tokens": call.prompt_tokens,
        "completion_tokens": call.completion_tokens,
    }
