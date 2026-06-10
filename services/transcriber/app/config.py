"""Environment-driven configuration for azure-transcriber.

All configuration comes from environment variables; no secrets are committed.
See ``.env.example`` for the full list with comments.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional


def _get(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val


# env name that supplies a per-model deployment override
_DEPLOYMENT_ENV = {
    "gpt-4o-transcribe": "AZURE_OPENAI_TRANSCRIBE_DEPLOYMENT",
    "gpt-4o-mini-transcribe": "AZURE_OPENAI_TRANSCRIBE_MINI_DEPLOYMENT",
    "gpt-4o-transcribe-diarize": "AZURE_OPENAI_TRANSCRIBE_DIARIZE_DEPLOYMENT",
    "whisper-1": "AZURE_OPENAI_WHISPER_DEPLOYMENT",
}


@dataclass
class Settings:
    # Which logical model the adapter uses. One of the capability-table keys
    # (see providers/__init__.py). Switching models is a one-line env change.
    # Default backend is "openrouter".
    transcriber_model: str = "openrouter"

    # ---- OpenRouter (default backend) ----
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # OpenRouter slugs are namespaced (provider/model), e.g. openai/gpt-4o-transcribe.
    # NOTE: OpenRouter STT returns text only — no word/segment timestamps.
    openrouter_transcribe_model: str = "openai/gpt-4o-transcribe"
    openrouter_referer: Optional[str] = None   # optional app-attribution header
    openrouter_title: Optional[str] = None     # optional app-attribution header

    # ---- Azure OpenAI (/audio/transcriptions: gpt-4o-transcribe*, whisper) ----
    azure_openai_endpoint: Optional[str] = None       # https://{res}.openai.azure.com
    azure_openai_api_key: Optional[str] = None
    azure_openai_api_version: str = "2025-04-01-preview"
    azure_use_aad: bool = False                        # Entra ID instead of api-key
    # Deployment-name resolution: per-model override -> single AZURE_OPENAI_DEPLOYMENT
    # -> the model id itself. On Azure the request 'model' field must be the
    # deployment name (Azure deviation from the OpenAI spec).
    azure_openai_deployment: Optional[str] = None
    deployment_overrides: Dict[str, str] = field(default_factory=dict)

    # ---- Azure AI Speech (LLM Speech / MAI-Transcribe-1) ----
    azure_speech_endpoint: Optional[str] = None        # https://{res}.cognitiveservices.azure.com
    azure_speech_key: Optional[str] = None
    azure_speech_region: Optional[str] = None
    azure_speech_api_version: str = "2025-10-15"
    mai_model_id: str = "mai-transcribe-1"

    # ---- Inbound (what Vexa's bot sends us) ----
    inbound_auth_token: Optional[str] = None           # if set, require matching Bearer/X-API-Key

    # ---- Behaviour ----
    request_timeout_s: float = 25.0                    # keep < bot's 30s client timeout
    max_retries: int = 2
    retry_base_ms: int = 500
    busy_retry_after_s: int = 1
    # Azure transcription verbose_json usually omits language_probability, and
    # Vexa's bot discards auto-detected segments below 0.3. Default high to avoid
    # spurious drops; lower it if you want Vexa to keep re-detecting language.
    default_language_probability: float = 1.0
    log_level: str = "INFO"

    def deployment_for(self, model_id: str) -> str:
        if model_id in self.deployment_overrides:
            return self.deployment_overrides[model_id]
        if self.azure_openai_deployment:
            return self.azure_openai_deployment
        return model_id


def load_settings() -> Settings:
    overrides: Dict[str, str] = {}
    for model_id, env_name in _DEPLOYMENT_ENV.items():
        v = _get(env_name)
        if v:
            overrides[model_id] = v

    return Settings(
        transcriber_model=_get("TRANSCRIBER_MODEL", "openrouter"),
        openrouter_api_key=_get("OPENROUTER_API_KEY"),
        openrouter_base_url=_get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        openrouter_transcribe_model=_get("OPENROUTER_TRANSCRIBE_MODEL", "openai/gpt-4o-transcribe"),
        openrouter_referer=_get("OPENROUTER_REFERER"),
        openrouter_title=_get("OPENROUTER_TITLE"),
        azure_openai_endpoint=_get("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=_get("AZURE_OPENAI_API_KEY"),
        azure_openai_api_version=_get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        azure_use_aad=(_get("AZURE_USE_AAD", "false") or "").lower() in ("1", "true", "yes"),
        azure_openai_deployment=_get("AZURE_OPENAI_DEPLOYMENT"),
        deployment_overrides=overrides,
        azure_speech_endpoint=_get("AZURE_SPEECH_ENDPOINT"),
        azure_speech_key=_get("AZURE_SPEECH_KEY"),
        azure_speech_region=_get("AZURE_SPEECH_REGION"),
        azure_speech_api_version=_get("AZURE_SPEECH_API_VERSION", "2025-10-15"),
        mai_model_id=_get("MAI_MODEL_ID", "mai-transcribe-1"),
        # reuse the same token the bot already carries, unless overridden
        inbound_auth_token=_get("INBOUND_AUTH_TOKEN") or _get("TRANSCRIPTION_SERVICE_TOKEN"),
        request_timeout_s=float(_get("REQUEST_TIMEOUT_S", "25") or "25"),
        max_retries=int(_get("MAX_RETRIES", "2") or "2"),
        retry_base_ms=int(_get("RETRY_BASE_MS", "500") or "500"),
        busy_retry_after_s=int(_get("BUSY_RETRY_AFTER_S", "1") or "1"),
        default_language_probability=float(_get("DEFAULT_LANGUAGE_PROBABILITY", "1.0") or "1.0"),
        log_level=_get("LOG_LEVEL", "INFO"),
    )
