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
        logger.warning("TEAM_ROSTER is not valid JSON; ignoring it")
    return {}


@dataclass
class Settings:
    # openrouter (default) | azure | openai_compatible (LiteLLM proxy)
    model_mode: str = "openrouter"

    # ---- Azure OpenAI chat (default model = gpt-5.5, a reasoning model) ----
    azure_openai_endpoint: Optional[str] = None       # https://{res}.openai.azure.com
    azure_openai_api_key: Optional[str] = None
    azure_openai_api_version: str = "2025-04-01-preview"
    azure_openai_deployment: str = "gpt-5.5"
    azure_use_aad: bool = False
    # gpt-5.5 is a REASONING model: temperature is NOT supported, and you must use
    # max_completion_tokens (not max_tokens). Set reasoning_model=false only if you
    # switch the deployment to a non-reasoning model (e.g. gpt-4.1).
    reasoning_model: bool = True
    llm_temperature: Optional[float] = None           # only sent if reasoning_model is False
    max_completion_tokens: int = 2000

    # ---- OpenRouter (default; openrouter.ai) ----
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-5.5"           # namespaced slug
    # Force OpenRouter to route only to a provider that honors response_format
    # (else structured outputs can be silently dropped).
    openrouter_require_parameters: bool = True
    openrouter_referer: Optional[str] = None
    openrouter_title: Optional[str] = None

    # ---- OpenAI-compatible proxy (when model_mode=openai_compatible) ----
    openai_compat_base_url: Optional[str] = None       # e.g. http://litellm:4000/v1
    openai_compat_api_key: Optional[str] = None
    openai_compat_model: str = "gpt-5.5"

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
        model_mode=_get("MODEL_MODE", "openrouter"),
        openrouter_api_key=_get("OPENROUTER_API_KEY"),
        openrouter_base_url=_get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        openrouter_model=_get("OPENROUTER_MODEL", "openai/gpt-5.5"),
        openrouter_require_parameters=(_get("OPENROUTER_REQUIRE_PARAMETERS", "true") or "").lower() in ("1", "true", "yes"),
        openrouter_referer=_get("OPENROUTER_REFERER"),
        openrouter_title=_get("OPENROUTER_TITLE"),
        azure_openai_endpoint=_get("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=_get("AZURE_OPENAI_API_KEY"),
        azure_openai_api_version=_get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        azure_openai_deployment=_get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.5"),
        azure_use_aad=(_get("AZURE_USE_AAD", "false") or "").lower() in ("1", "true", "yes"),
        reasoning_model=(_get("REASONING_MODEL", "true") or "").lower() in ("1", "true", "yes"),
        llm_temperature=(float(_get("LLM_TEMPERATURE")) if _get("LLM_TEMPERATURE") else None),
        max_completion_tokens=int(_get("MAX_COMPLETION_TOKENS", "2000") or "2000"),
        openai_compat_base_url=_get("OPENAI_COMPAT_BASE_URL"),
        openai_compat_api_key=_get("OPENAI_COMPAT_API_KEY"),
        openai_compat_model=_get("OPENAI_COMPAT_MODEL", "gpt-5.5"),
        meeting_api_internal_url=_get("MEETING_API_INTERNAL_URL", "http://meeting-api:8080"),
        internal_api_secret=_get("INTERNAL_API_SECRET", "vexa-internal-secret"),
        team_roster=_parse_roster(_get("TEAM_ROSTER")),
        kanban_api_url=_get("KANBAN_API_URL"),
        kanban_api_key=_get("KANBAN_API_KEY"),
        request_timeout_s=float(_get("REQUEST_TIMEOUT_S", "60") or "60"),
        log_level=_get("LOG_LEVEL", "INFO"),
    )
