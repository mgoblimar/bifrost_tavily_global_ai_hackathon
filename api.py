"""Carbon Date verification API: a freshness check any AI application can call.

Run with:  uvicorn api:app --port 8600

    POST /v1/verify   {"answer": "<text your model produced>"}
    ->   per-claim verdict, current value, freshness score and sources

If CARBON_DATE_API_KEY is set, callers must send it in the X-API-Key header.
"""

import hmac
import logging
import os

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from core.config import ConfigError, load_settings
from core.llm import LLMError
from core.trusted import parse_domains
from stale_detector.pipeline import MAX_ANSWER_CHARS, analyze
from stale_detector.serialize import report_to_dict

logger = logging.getLogger("carbon_date.api")

app = FastAPI(
    title="Carbon Date verification API",
    description="Checks the time-sensitive claims in an AI-generated answer "
    "against the live web and returns a freshness score for each.",
    version="1.0.0",
)


class VerifyRequest(BaseModel):
    answer: str = Field(
        min_length=1,
        max_length=MAX_ANSWER_CHARS,
        description="The AI-generated text to check.",
    )
    trusted_domains: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Official sites to search first, e.g. ['fda.gov.ph'].",
    )
    context: str = Field(
        default="",
        max_length=500,
        description="Optional note on what the answer is about or for.",
    )


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce the API key when one is configured; open on localhost otherwise."""
    expected = os.getenv("CARBON_DATE_API_KEY", "").strip()
    if not expected:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/verify", dependencies=[Depends(require_api_key)])
def verify(request: VerifyRequest) -> dict:
    """Check one AI-generated answer and return per-claim freshness."""
    if not request.answer.strip():
        raise HTTPException(status_code=422, detail="answer must not be blank.")
    try:
        settings = load_settings()
        report = analyze(
            settings,
            request.answer,
            trusted_domains=parse_domains(", ".join(request.trusted_domains)),
            context=request.context.strip(),
        )
    except ConfigError as exc:
        logger.error("Verification API is misconfigured: %s", exc)
        raise HTTPException(
            status_code=500, detail="The verification service is not configured."
        ) from exc
    except LLMError as exc:
        logger.warning("Model gateway failed during verification: %s", exc)
        raise HTTPException(
            status_code=502, detail="The model gateway is unavailable. Try again shortly."
        ) from exc
    return report_to_dict(report)
