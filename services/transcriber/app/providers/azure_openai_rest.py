"""Azure OpenAI ``/audio/transcriptions`` provider — gpt-4o-transcribe family.

POSTs the WAV chunk to Azure OpenAI and returns Vexa verbose_json **with word +
segment timestamps** (``response_format=verbose_json`` +
``timestamp_granularities[] = word, segment``). This is the timestamp-capable
alternative to the OpenRouter STT backend (which is text-only) — the bot needs
word timestamps to attribute speech to the correct speaker when several mics are
open at once.

On Azure the request ``model`` form field must be the DEPLOYMENT name (Azure's
deviation from the OpenAI spec), so ``AZURE_OPENAI_DEPLOYMENT`` overrides the
logical model id.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .. import schema
from .base import Capability, ProviderError, TranscriptionProvider
from .http import post_with_retry

logger = logging.getLogger("transcriber.azure")


class AzureOpenAIRestProvider(TranscriptionProvider):
    def __init__(self, model_id: str, capability: Capability, settings, http_client):
        self.model_id = model_id
        self.capability = capability
        self.settings = settings
        self.http = http_client
        if not settings.azure_openai_endpoint:
            raise ProviderError("AZURE_OPENAI_ENDPOINT is not configured", status_code=500)
        # On Azure the 'model' form field must be the deployment name.
        self.deployment = settings.azure_openai_deployment or model_id

    def _url(self) -> str:
        base = self.settings.azure_openai_endpoint.rstrip("/")
        return (f"{base}/openai/deployments/{self.deployment}/audio/transcriptions"
                f"?api-version={self.settings.azure_openai_api_version}")

    def _headers(self) -> Dict[str, str]:
        if not self.settings.azure_openai_api_key:
            raise ProviderError("AZURE_OPENAI_API_KEY is not configured", status_code=500)
        return {"api-key": self.settings.azure_openai_api_key}

    def _form(self, language: Optional[str], prompt: Optional[str]) -> List[Tuple[str, str]]:
        data: List[Tuple[str, str]] = [
            ("model", self.deployment),
            ("response_format", "verbose_json"),
            # Word timestamps are the whole point of this backend — always request
            # them so the bot can split a chunk across speakers.
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
        ]
        if prompt:
            data.append(("prompt", prompt))
        if language:
            data.append(("language", language))
        return data

    async def transcribe(self, audio, *, filename="audio.wav", content_type="audio/wav",
                         language=None, prompt=None) -> Dict[str, Any]:
        resp = await post_with_retry(
            self.http, self._url(),
            headers=self._headers(),
            data=self._form(language, prompt),
            files={"file": (filename, audio, content_type)},
            settings=self.settings, label=self.model_id,
        )
        return schema.from_openai_verbose(
            resp, fallback_language=language,
            default_language_probability=self.settings.default_language_probability)
