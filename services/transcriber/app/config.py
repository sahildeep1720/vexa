"""Environment-driven configuration for transcriber.

All configuration comes from environment variables; no secrets are committed.
See ``.env.example`` for the full list with comments.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


# Deliberate per-service copy of this tiny env reader (keeps the service self-contained;
# no shared lib dependency just for one helper).
def _get(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val


@dataclass
class Settings:
    # Which logical model the adapter uses. One of the capability-table keys
    # (see providers/__init__.py). Switching models is a one-line env change.
    # Default backend is "openrouter".
    transcriber_model: str = "openrouter"

    # ---- OpenRouter (the backend) ----
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # OpenRouter slugs are namespaced (provider/model), e.g. openai/gpt-4o-transcribe.
    # NOTE: OpenRouter STT returns text only — no word/segment timestamps.
    openrouter_transcribe_model: str = "openai/gpt-4o-transcribe"
    openrouter_referer: Optional[str] = None   # optional app-attribution header
    openrouter_title: Optional[str] = None     # optional app-attribution header

    # ---- Inbound (what Vexa's bot sends us) ----
    inbound_auth_token: Optional[str] = None           # if set, require matching Bearer/X-API-Key

    # ---- Behaviour ----
    request_timeout_s: float = 25.0                    # keep < bot's 30s client timeout
    max_retries: int = 2
    retry_base_ms: int = 500
    busy_retry_after_s: int = 1
    # OpenRouter STT omits language_probability, and Vexa's bot discards
    # auto-detected segments below 0.3. Default high to avoid spurious drops;
    # lower it if you want Vexa to keep re-detecting language.
    default_language_probability: float = 1.0
    log_level: str = "INFO"


def load_settings() -> Settings:
    return Settings(
        transcriber_model=_get("TRANSCRIBER_MODEL", "openrouter"),
        openrouter_api_key=_get("OPENROUTER_API_KEY"),
        openrouter_base_url=_get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        openrouter_transcribe_model=_get("OPENROUTER_TRANSCRIBE_MODEL", "openai/gpt-4o-transcribe"),
        openrouter_referer=_get("OPENROUTER_REFERER"),
        openrouter_title=_get("OPENROUTER_TITLE"),
        # reuse the same token the bot already carries, unless overridden
        inbound_auth_token=_get("INBOUND_AUTH_TOKEN") or _get("TRANSCRIPTION_SERVICE_TOKEN"),
        request_timeout_s=float(_get("REQUEST_TIMEOUT_S", "25") or "25"),
        max_retries=int(_get("MAX_RETRIES", "2") or "2"),
        retry_base_ms=int(_get("RETRY_BASE_MS", "500") or "500"),
        busy_retry_after_s=int(_get("BUSY_RETRY_AFTER_S", "1") or "1"),
        default_language_probability=float(_get("DEFAULT_LANGUAGE_PROBABILITY", "1.0") or "1.0"),
        log_level=_get("LOG_LEVEL", "INFO"),
    )
