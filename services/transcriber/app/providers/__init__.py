"""Capability table + provider factory.

The capability table is the single source of truth for what each model can do.
``streams`` records whether the model has an Azure streaming surface (Realtime/SSE)
— it is informational only, because Vexa's hook is per-chunk REST and never streams
audio frames to us (see providers/realtime.py for why).
"""
from __future__ import annotations

from typing import Dict

from ..config import Settings
from .azure_openai_rest import AzureOpenAIRestProvider
from .azure_speech_llm import AzureSpeechLLMProvider
from .base import Capability, ProviderError, TranscriptionProvider

CAPABILITIES: Dict[str, Capability] = {
    # Default backend. OpenRouter STT is text-only (no word/segment timestamps);
    # the provider synthesizes a single full-chunk segment.
    "openrouter":                Capability("openrouter",        streams=False, diarizes=False, word_timestamps=False),
    "gpt-4o-transcribe":         Capability("azure_openai_rest", streams=True,  diarizes=False, word_timestamps=True),
    "gpt-4o-mini-transcribe":    Capability("azure_openai_rest", streams=True,  diarizes=False, word_timestamps=True),
    "gpt-4o-transcribe-diarize": Capability("azure_openai_rest", streams=False, diarizes=True,  word_timestamps=False),
    "whisper-1":                 Capability("azure_openai_rest", streams=False, diarizes=False, word_timestamps=True),
    "MAI-Transcribe-1":          Capability("azure_speech_llm",  streams=False, diarizes=False, word_timestamps=True),
}

# Convenience aliases for the TRANSCRIBER_MODEL env value.
_ALIASES = {
    "whisper": "whisper-1",
    "mai-transcribe-1": "MAI-Transcribe-1",
    "mai": "MAI-Transcribe-1",
}


def resolve_model(model_id: str) -> str:
    if model_id in CAPABILITIES:
        return model_id
    if model_id in _ALIASES:
        return _ALIASES[model_id]
    if model_id.lower() in _ALIASES:
        return _ALIASES[model_id.lower()]
    raise ValueError(f"Unknown TRANSCRIBER_MODEL '{model_id}'. Known: {sorted(CAPABILITIES)}")


def build_provider(settings: Settings, http_client) -> TranscriptionProvider:
    model_id = resolve_model(settings.transcriber_model)
    cap = CAPABILITIES[model_id]
    if cap.api_kind == "azure_openai_rest":
        return AzureOpenAIRestProvider(model_id, cap, settings, http_client)
    if cap.api_kind == "azure_speech_llm":
        return AzureSpeechLLMProvider(model_id, cap, settings, http_client)
    if cap.api_kind == "openrouter":
        from .openrouter import OpenRouterTranscriptionProvider
        return OpenRouterTranscriptionProvider(model_id, cap, settings, http_client)
    if cap.api_kind == "azure_openai_realtime":
        from .realtime import AzureRealtimeProvider
        return AzureRealtimeProvider(model_id, cap, settings, http_client)
    raise ProviderError(f"Unsupported api_kind '{cap.api_kind}'", status_code=500)
