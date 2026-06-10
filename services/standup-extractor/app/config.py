"""Environment-driven configuration for standup-extractor.

All configuration comes from environment variables; no secrets are committed.
See ``.env.example`` for the full list with comments.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("standup_extractor.config")


def _get(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val


def _parse_roster(raw: Optional[str]) -> Dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (ValueError, TypeError):
        # load_settings() runs at import time, before main.py calls
        # logging.basicConfig(), so this warning has no configured handler. It is
        # still surfaced to stderr by Python's "last resort" handler.
        logger.warning("TEAM_ROSTER is not valid JSON; ignoring it")
    return {}


@dataclass
class Settings:
    # ---- OpenRouter chat (default model = openai/gpt-5.5, a reasoning model) ----
    openrouter_api_key: Optional[str] = None
    # Any OpenAI-compatible /chat/completions endpoint (OpenRouter or a proxy).
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-5.5"           # namespaced slug
    # Force OpenRouter to route only to a provider that honors response_format
    # (else structured outputs can be silently dropped). Set false for proxies
    # that reject the `provider` field.
    openrouter_require_parameters: bool = True
    openrouter_referer: Optional[str] = None
    openrouter_title: Optional[str] = None

    # gpt-5.5 is a REASONING model: temperature is NOT supported. Set
    # reasoning_model=false only if you switch to a non-reasoning model
    # (e.g. openai/gpt-4.1) and want a deterministic temperature.
    reasoning_model: bool = True
    llm_temperature: Optional[float] = None           # only sent if reasoning_model is False
    max_completion_tokens: int = 2000

    # ---- Vexa internal transcript fetch ----
    meeting_api_internal_url: str = "http://meeting-api:8080"
    internal_api_secret: str = "vexa-internal-secret"

    # ---- Speaker label -> real name map (JSON) ----
    team_roster: Dict[str, str] = field(default_factory=dict)

    # ---- Kanban (stub) ----
    kanban_api_url: Optional[str] = None
    kanban_api_key: Optional[str] = None

    # ---- Behaviour ----
    request_timeout_s: float = 60.0                    # LLM calls can be slow
    log_level: str = "INFO"


def load_settings() -> Settings:
    return Settings(
        openrouter_api_key=_get("OPENROUTER_API_KEY"),
        openrouter_base_url=_get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        openrouter_model=_get("OPENROUTER_MODEL", "openai/gpt-5.5"),
        openrouter_require_parameters=(_get("OPENROUTER_REQUIRE_PARAMETERS", "true") or "").lower() in ("1", "true", "yes"),
        openrouter_referer=_get("OPENROUTER_REFERER"),
        openrouter_title=_get("OPENROUTER_TITLE"),
        reasoning_model=(_get("REASONING_MODEL", "true") or "").lower() in ("1", "true", "yes"),
        llm_temperature=(float(_get("LLM_TEMPERATURE")) if _get("LLM_TEMPERATURE") else None),
        max_completion_tokens=int(_get("MAX_COMPLETION_TOKENS", "2000") or "2000"),
        meeting_api_internal_url=_get("MEETING_API_INTERNAL_URL", "http://meeting-api:8080"),
        internal_api_secret=_get("INTERNAL_API_SECRET", "vexa-internal-secret"),
        team_roster=_parse_roster(_get("TEAM_ROSTER")),
        kanban_api_url=_get("KANBAN_API_URL"),
        kanban_api_key=_get("KANBAN_API_KEY"),
        request_timeout_s=float(_get("REQUEST_TIMEOUT_S", "60") or "60"),
        log_level=_get("LOG_LEVEL", "INFO"),
    )
