"""Settings loaded from the environment (.env)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Raised when a required setting is missing."""


@dataclass(frozen=True)
class ModelRoute:
    """A primary model and the model Bifrost should fall back to."""

    primary: str
    fallback: str


@dataclass(frozen=True)
class Settings:
    bifrost_url: str
    bifrost_virtual_key: str
    tavily_api_key: str
    fast: ModelRoute
    strong: ModelRoute


def load_settings() -> Settings:
    tavily_api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not tavily_api_key:
        raise ConfigError("TAVILY_API_KEY is missing. Add it to your .env file.")

    virtual_key = os.getenv("BIFROST_VIRTUAL_KEY", "").strip()
    if not virtual_key:
        raise ConfigError("BIFROST_VIRTUAL_KEY is missing. Add it to your .env file.")

    return Settings(
        bifrost_url=os.getenv("BIFROST_URL", "http://localhost:8090").rstrip("/"),
        bifrost_virtual_key=virtual_key,
        tavily_api_key=tavily_api_key,
        fast=ModelRoute(
            primary=os.getenv("FAST_MODEL", "groq/openai/gpt-oss-20b"),
            fallback=os.getenv("FAST_FALLBACK", "gemini/gemini-flash-lite-latest"),
        ),
        strong=ModelRoute(
            primary=os.getenv("STRONG_MODEL", "gemini/gemini-3.5-flash"),
            fallback=os.getenv("STRONG_FALLBACK", "groq/openai/gpt-oss-120b"),
        ),
    )
