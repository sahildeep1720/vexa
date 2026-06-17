"""Capability table + provider factory.

The capability table is the single source of truth for what each backend can do.
Two backends:
  - ``openrouter``        — text-only STT (no timestamps); chunk-level attribution.
  - ``gpt-4o-transcribe`` — Azure OpenAI; returns word + segment timestamps, so the
    bot can attribute speech per-speaker. Pick it with TRANSCRIBER_MODEL.
"""
from __future__ import annotations

from typing import Dict

from ..config import Settings
from .base import Capability, ProviderError, TranscriptionProvider
from .openrouter import OpenRouterTranscriptionProvider

CAPABILITIES: Dict[str, Capability] = {
    # OpenRouter STT is text-only (no word/segment timestamps); the provider
    # synthesizes a single full-chunk segment.
    "openrouter": Capability("openrouter", word_timestamps=False),
    # Azure OpenAI STT — verbose_json with word + segment timestamps.
    "gpt-4o-transcribe":      Capability("azure_openai_rest", word_timestamps=True),
    "gpt-4o-mini-transcribe": Capability("azure_openai_rest", word_timestamps=True),
    "whisper-1":              Capability("azure_openai_rest", word_timestamps=True),
}

# Convenience aliases for the TRANSCRIBER_MODEL env value.
_ALIASES = {"whisper": "whisper-1"}


def resolve_model(model_id: str) -> str:
    if model_id in CAPABILITIES:
        return model_id
    if model_id in _ALIASES:
        return _ALIASES[model_id]
    raise ValueError(f"Unknown TRANSCRIBER_MODEL '{model_id}'. Known: {sorted(CAPABILITIES)}")


def build_provider(settings: Settings, http_client) -> TranscriptionProvider:
    model_id = resolve_model(settings.transcriber_model)
    cap = CAPABILITIES[model_id]
    if cap.api_kind == "openrouter":
        return OpenRouterTranscriptionProvider(model_id, cap, settings, http_client)
    if cap.api_kind == "azure_openai_rest":
        from .azure_openai_rest import AzureOpenAIRestProvider
        return AzureOpenAIRestProvider(model_id, cap, settings, http_client)
    raise ProviderError(f"Unsupported api_kind '{cap.api_kind}'", status_code=500)
