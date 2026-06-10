"""Provider abstraction + capability metadata for the Azure transcription backends."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class Capability:
    api_kind: str          # azure_openai_rest | azure_speech_llm | azure_openai_realtime
    streams: bool          # model has an Azure streaming surface (Realtime/SSE) — informational
    diarizes: bool         # model returns speaker labels
    word_timestamps: bool  # model can return word-level timestamps


class ProviderError(Exception):
    """Upstream failure. ``status_code`` is what we return to Vexa.

    Returning 503 lets Vexa's existing client-side retry/backoff kick in; we
    never raise an exception out to the meeting — a failed chunk just retries.
    """

    def __init__(self, message: str, status_code: int = 502, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class TranscriptionProvider(ABC):
    model_id: str
    capability: Capability

    @abstractmethod
    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "audio.wav",
        content_type: str = "audio/wav",
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        max_speech_duration_s: Optional[float] = None,
        min_silence_duration_ms: Optional[int] = None,
        want_word_timestamps: bool = True,
    ) -> Dict[str, Any]:
        """Transcribe one audio chunk; return Vexa-shaped verbose_json."""
        raise NotImplementedError
