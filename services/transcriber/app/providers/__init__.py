"""Capability table + provider factory.

The capability table is the single source of truth for what the backend can do.
OpenRouter is the only backend; switching the OpenRouter model is a one-line env
change (``OPENROUTER_TRANSCRIBE_MODEL``).
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
}


def resolve_model(model_id: str) -> str:
    if model_id in CAPABILITIES:
        return model_id
    raise ValueError(f"Unknown TRANSCRIBER_MODEL '{model_id}'. Known: {sorted(CAPABILITIES)}")


def build_provider(settings: Settings, http_client) -> TranscriptionProvider:
    model_id = resolve_model(settings.transcriber_model)
    cap = CAPABILITIES[model_id]
    if cap.api_kind == "openrouter":
        return OpenRouterTranscriptionProvider(model_id, cap, settings, http_client)
    raise ProviderError(f"Unsupported api_kind '{cap.api_kind}'", status_code=500)
