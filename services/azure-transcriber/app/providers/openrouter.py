"""OpenRouter transcription provider.

Calls OpenRouter's dedicated STT endpoint POST {base}/audio/transcriptions, which
takes a JSON body with base64 audio (NOT multipart) and returns `{text, usage}` —
TEXT ONLY, with NO segment/word timestamps and no verbose_json.

To keep Vexa's bot pipeline working (it expects segments with start/end to drive
its sliding-window confirmation), we synthesize ONE segment spanning the whole
chunk: [0, chunk_duration]. Word-level speaker attribution therefore degrades to
chunk granularity — acceptable for per-speaker capture (Google Meet), coarser for
mixed audio (Teams). See README for the tradeoff.
"""
from __future__ import annotations

import base64
import io
import logging
import wave
from typing import Any, Dict, Optional

from .. import schema
from .azure_openai_rest import post_with_retry
from .base import ProviderError, TranscriptionProvider

logger = logging.getLogger("azure_transcriber.openrouter")


class OpenRouterTranscriptionProvider(TranscriptionProvider):
    def __init__(self, model_id, capability, settings, http_client):
        self.model_id = model_id
        self.capability = capability
        self.settings = settings
        self.http = http_client
        if not settings.openrouter_api_key:
            raise ProviderError("OPENROUTER_API_KEY is not configured", status_code=500)
        # The OpenRouter model slug is namespaced (e.g. openai/gpt-4o-transcribe).
        self.slug = settings.openrouter_transcribe_model

    def _url(self) -> str:
        return f"{self.settings.openrouter_base_url.rstrip('/')}/audio/transcriptions"

    def _headers(self) -> Dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        # Optional app-attribution headers (only affect OpenRouter dashboard ranking).
        if self.settings.openrouter_referer:
            h["HTTP-Referer"] = self.settings.openrouter_referer
        if self.settings.openrouter_title:
            h["X-Title"] = self.settings.openrouter_title
        return h

    async def transcribe(self, audio, *, filename="audio.wav", content_type="audio/wav",
                         language=None, prompt=None, max_speech_duration_s=None,
                         min_silence_duration_ms=None, want_word_timestamps=True) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self.slug,
            "input_audio": {
                "data": base64.b64encode(audio).decode("ascii"),  # raw base64, NOT a data URI
                "format": _format_from(filename, content_type),
            },
        }
        if language:
            body["language"] = language

        resp = await post_with_retry(self.http, self._url(), headers=self._headers(),
                                     json_body=body, settings=self.settings, label=self.model_id)
        text = resp.get("text") if isinstance(resp, dict) else None
        duration = _wav_duration(audio)
        return schema.from_openrouter_text(
            text, duration=duration, fallback_language=language,
            default_language_probability=self.settings.default_language_probability)


def _format_from(filename: str, content_type: str) -> str:
    name = (filename or "").lower()
    for ext in ("wav", "mp3", "flac", "m4a", "ogg", "webm", "aac"):
        if name.endswith("." + ext):
            return ext
    if content_type and "/" in content_type:
        sub = content_type.split("/", 1)[1]
        return "wav" if sub in ("x-wav", "wave") else sub
    return "wav"


def _wav_duration(audio: bytes) -> float:
    """Seconds of audio, parsed from the WAV header; falls back to a 16k-mono-16bit
    estimate if the header can't be read (so the synthesized segment still spans
    roughly the chunk)."""
    try:
        with wave.open(io.BytesIO(audio)) as w:
            frames = w.getnframes()
            rate = w.getframerate() or 16000
            return frames / float(rate)
    except (wave.Error, EOFError, OSError):
        # crude fallback: assume 16kHz mono 16-bit PCM, minus a 44-byte header
        return max(0.0, (len(audio) - 44) / (16000.0 * 2.0))
