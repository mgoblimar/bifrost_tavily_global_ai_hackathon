"""Trusted ("official") source sites chosen by the user.

A verdict that rests on a regulator's or the company's own site deserves more
trust than one resting on news coverage. The user names the sites; the app
searches them first and labels which kind of evidence each verdict rests on.
"""

import re
from urllib.parse import urlparse

MAX_TRUSTED_DOMAINS = 8
DOMAIN_PATTERN = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")

PRESETS: dict[str, tuple[str, ...]] = {
    "None": (),
    "Philippine health regulators": ("fda.gov.ph", "doh.gov.ph", "philhealth.gov.ph"),
}


def parse_domains(text: str) -> tuple[str, ...]:
    """Turn 'https://www.Example.com/page, fda.gov.ph' into clean domain names.

    Anything that is not a plain domain is dropped, so user input can never
    become part of a search query or URL in an unexpected shape.
    """
    domains: list[str] = []
    for raw in re.split(r"[,\s]+", text.strip().lower()):
        if not raw:
            continue
        host = urlparse(raw if "//" in raw else f"//{raw}").hostname or ""
        host = host.removeprefix("www.")
        if DOMAIN_PATTERN.match(host) and host not in domains:
            domains.append(host)
    return tuple(domains[:MAX_TRUSTED_DOMAINS])


def is_trusted(url: str, trusted_domains: tuple[str, ...]) -> bool:
    """True when the URL's host is a trusted domain or one of its subdomains."""
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in trusted_domains)
