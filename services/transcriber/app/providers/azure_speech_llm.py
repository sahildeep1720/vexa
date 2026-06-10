"""Azure AI Speech fast-transcription provider (LLM Speech / MAI-Transcribe-1).

Calls ``POST /speechtotext/transcriptions:transcribe`` with enhancedMode set to
``mai-transcribe-1``. Azure returns its native JSON (ms offsets, phrases/words);
schema.from_azure_speech maps it to Vexa's verbose_json (float seconds). Batch /
near-real-time, no diarization.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

from .. import schema
from .azure_openai_rest import post_with_retry
from .base import ProviderError, TranscriptionProvider

logger = logging.getLogger("azure_transcriber.azure_speech_llm")


class AzureSpeechLLMProvider(TranscriptionProvider):
    def __init__(self, model_id, capability, settings, http_client):
        self.model_id = model_id
        self.capability = capability
        self.settings = settings
        self.http = http_client
        if not settings.azure_speech_endpoint:
            raise ProviderError("AZURE_SPEECH_ENDPOINT is not configured", status_code=500)
        if not settings.azure_speech_key and not settings.azure_use_aad:
            raise ProviderError("AZURE_SPEECH_KEY is not configured", status_code=500)

    def _url(self) -> str:
        base = self.settings.azure_speech_endpoint.rstrip("/")
        return (f"{base}/speechtotext/transcriptions:transcribe"
                f"?api-version={self.settings.azure_speech_api_version}")

    def _headers(self) -> Dict[str, str]:
        if self.settings.azure_use_aad:
            return {}  # caller-provided bearer / managed identity proxy
        return {"Ocp-Apim-Subscription-Key": self.settings.azure_speech_key}

    async def transcribe(self, audio, *, filename="audio.wav", content_type="audio/wav",
                         language=None, prompt=None, max_speech_duration_s=None,
                         min_silence_duration_ms=None, want_word_timestamps=True) -> Dict[str, Any]:
        definition: Dict[str, Any] = {
            "enhancedMode": {"enabled": True, "model": self.settings.mai_model_id}
        }
        if language:
            definition["locales"] = [language]
        data: List[Tuple[str, str]] = [("definition", json.dumps(definition))]
        resp = await post_with_retry(
            self.http, self._url(),
            headers=self._headers(),
            data=data,
            files={"audio": (filename, audio, content_type)},
            settings=self.settings, label=self.model_id,
        )
        return schema.from_azure_speech(
            resp, fallback_language=language,
            default_language_probability=self.settings.default_language_probability)
