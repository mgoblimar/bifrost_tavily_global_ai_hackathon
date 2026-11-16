"""Chat client for the Bifrost gateway.

Every model call in the project goes through here, so Bifrost handles provider
keys, routing and automatic fallback. We call the gateway's native endpoint
directly (not an SDK) so we can send `fallbacks` and read back which provider
actually served the request.
"""

import json
import time
from dataclasses import dataclass

import requests

from core.config import ModelRoute

REQUEST_TIMEOUT_SECONDS = 60
# Bifrost already fails over to the other provider. If both are briefly rate
# limited or overloaded (common on free tiers), wait and try the pair again.
RETRYABLE_STATUS_CODES = (429, 503)
RETRY_DELAYS_SECONDS = (8, 20)


class LLMError(RuntimeError):
    """Raised when the gateway cannot return a usable answer."""


@dataclass(frozen=True)
class LLMCall:
    """One completed model call, with the routing facts Bifrost reported."""

    content: str
    requested_model: str
    served_by: str
    is_fallback: bool
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float


def chat_json(
    bifrost_url: str, virtual_key: str, route: ModelRoute, system: str, user: str
) -> tuple[dict, LLMCall]:
    """Send a prompt that must be answered in JSON; return (parsed, call record)."""
    payload = {
        "model": route.primary,
        "fallbacks": [route.fallback],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    response = _post(bifrost_url, virtual_key, payload)
    for delay in RETRY_DELAYS_SECONDS:
        if response.status_code not in RETRYABLE_STATUS_CODES:
            break
        time.sleep(delay)
        response = _post(bifrost_url, virtual_key, payload)

    if response.status_code in RETRYABLE_STATUS_CODES:
        raise LLMError(
            f"Both model providers are rate-limited or overloaded "
            f"(HTTP {response.status_code}). Wait a minute and try again."
        )
    if response.status_code != 200:
        raise LLMError(
            f"Bifrost returned HTTP {response.status_code}: {response.text[:300]}"
        )

    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("Bifrost returned an unexpected response shape.") from exc

    call = _build_call(body, content, route.primary)
    return parse_json_object(content), call


def _post(bifrost_url: str, virtual_key: str, payload: dict) -> requests.Response:
    try:
        return requests.post(
            f"{bifrost_url}/v1/chat/completions",
            json=payload,
            headers={"x-bf-vk": virtual_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.ConnectionError as exc:
        raise LLMError(
            f"Cannot reach the Bifrost gateway at {bifrost_url}. "
            "Start it with scripts/start_bifrost.ps1."
        ) from exc
    except requests.RequestException as exc:
        raise LLMError(f"Request to Bifrost failed: {exc}") from exc


def _build_call(body: dict, content: str, requested_model: str) -> LLMCall:
    usage = body.get("usage") or {}
    extra = body.get("extra_fields") or {}
    routing = extra.get("routing_info") or {}
    provider = routing.get("provider") or extra.get("provider")
    model = routing.get("model") or body.get("model") or requested_model
    has_prefix = bool(provider) and model.startswith(f"{provider}/")
    served_by = f"{provider}/{model}" if provider and not has_prefix else model
    return LLMCall(
        content=content,
        requested_model=requested_model,
        served_by=served_by,
        is_fallback=bool(routing.get("is_fallback", False)),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        latency_ms=float(extra.get("latency") or 0),
    )


def parse_json_object(text: str) -> dict:
    """Parse a JSON object from model output, tolerating code fences and chatter."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("The model did not return a JSON object.")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError("The model returned malformed JSON.") from exc
    if not isinstance(parsed, dict):
        raise LLMError("The model did not return a JSON object.")
    return parsed
