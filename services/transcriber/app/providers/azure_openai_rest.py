"""Azure OpenAI ``/audio/transcriptions`` provider.

Serves the gpt-4o-transcribe family + whisper. POSTs the WAV chunk to Azure and
translates the response into Vexa's verbose_json. For the diarize model it uses
``diarized_json`` (segment-level only; no word timestamps).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .. import schema
from .base import ProviderError, TranscriptionProvider

logger = logging.getLogger("azure_transcriber.azure_openai_rest")


class AzureOpenAIRestProvider(TranscriptionProvider):
    def __init__(self, model_id, capability, settings, http_client):
        self.model_id = model_id
        self.capability = capability
        self.settings = settings
        self.http = http_client
        if not settings.azure_openai_endpoint:
            raise ProviderError("AZURE_OPENAI_ENDPOINT is not configured", status_code=500)
        # On Azure the 'model' form field must be the DEPLOYMENT name.
        self.deployment = settings.deployment_for(model_id)

    def _url(self) -> str:
        base = self.settings.azure_openai_endpoint.rstrip("/")
        return (f"{base}/openai/deployments/{self.deployment}/audio/transcriptions"
                f"?api-version={self.settings.azure_openai_api_version}")

    async def _headers(self) -> Dict[str, str]:
        if self.settings.azure_use_aad:
            return {"Authorization": f"Bearer {await _aad_token()}"}
        if not self.settings.azure_openai_api_key:
            raise ProviderError("AZURE_OPENAI_API_KEY is not configured", status_code=500)
        return {"api-key": self.settings.azure_openai_api_key}

    def _form(self, language: Optional[str], prompt: Optional[str],
              want_word_timestamps: bool) -> List[Tuple[str, str]]:
        data: List[Tuple[str, str]] = [("model", self.deployment)]
        if self.capability.diarizes:
            # diarize: diarized_json only; verbose_json/timestamp_granularities/prompt
            # are rejected by this model. chunking_strategy required for >30s audio.
            data.append(("response_format", "diarized_json"))
            data.append(("chunking_strategy", "auto"))
        else:
            data.append(("response_format", "verbose_json"))
            if self.capability.word_timestamps and want_word_timestamps:
                data.append(("timestamp_granularities[]", "word"))
                data.append(("timestamp_granularities[]", "segment"))
            if prompt:
                data.append(("prompt", prompt))
        if language:
            data.append(("language", language))
        return data

    async def transcribe(self, audio, *, filename="audio.wav", content_type="audio/wav",
                         language=None, prompt=None, max_speech_duration_s=None,
                         min_silence_duration_ms=None, want_word_timestamps=True) -> Dict[str, Any]:
        resp = await post_with_retry(
            self.http, self._url(),
            headers=await self._headers(),
            data=self._form(language, prompt, want_word_timestamps),
            files={"file": (filename, audio, content_type)},
            settings=self.settings, label=self.model_id,
        )
        if self.capability.diarizes:
            return schema.from_diarized(
                resp, fallback_language=language,
                default_language_probability=self.settings.default_language_probability)
        return schema.from_openai_verbose(
            resp, fallback_language=language,
            default_language_probability=self.settings.default_language_probability)


async def _aad_token() -> str:
    try:
        from azure.identity import DefaultAzureCredential  # optional dependency
    except ImportError as e:  # pragma: no cover - optional path
        raise ProviderError("AZURE_USE_AAD=true but azure-identity is not installed",
                            status_code=500) from e
    cred = DefaultAzureCredential()
    token = await asyncio.to_thread(cred.get_token, "https://ai.azure.com/.default")
    return token.token


async def post_with_retry(http: httpx.AsyncClient, url: str, *, headers, settings, label: str,
                          data=None, files=None, json_body=None) -> Dict[str, Any]:
    """POST (multipart or JSON) with bounded retry on 429/503 + network errors.

    Audio is passed as bytes / a JSON body, so retries are safe. Pass either
    (data, files) for multipart or json_body for an application/json POST.
    """
    attempt = 0
    while True:
        try:
            if json_body is not None:
                resp = await http.post(url, headers=headers, json=json_body,
                                       timeout=settings.request_timeout_s)
            else:
                resp = await http.post(url, headers=headers, data=data, files=files,
                                       timeout=settings.request_timeout_s)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            if attempt >= settings.max_retries:
                raise ProviderError(f"{label}: upstream network error: {e}",
                                    status_code=503, retry_after=settings.busy_retry_after_s)
            await asyncio.sleep(settings.retry_base_ms * (2 ** attempt) / 1000.0)
            attempt += 1
            continue

        if resp.status_code in (429, 503):
            wait = _retry_after(resp, settings)
            if attempt >= settings.max_retries:
                raise ProviderError(f"{label}: upstream busy ({resp.status_code})",
                                    status_code=503, retry_after=wait)
            await asyncio.sleep(wait)
            attempt += 1
            continue

        if resp.status_code >= 400:
            raise ProviderError(f"{label}: Azure returned {resp.status_code}: {resp.text[:500]}",
                                status_code=502)
        return resp.json()


def _retry_after(resp: httpx.Response, settings) -> int:
    ra = resp.headers.get("Retry-After")
    if not ra:
        return settings.busy_retry_after_s
    try:
        return max(1, int(ra))
    except ValueError:
        return settings.busy_retry_after_s
