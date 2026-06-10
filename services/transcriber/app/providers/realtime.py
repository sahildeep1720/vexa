"""Azure OpenAI Realtime (WebSocket) transcription — intentionally NOT wired into
the live Vexa hook.

Phase 0 discovery established that Vexa's bot does NOT stream audio frames: it
POSTs discrete, complete WAV chunks to a stateless ``/v1/audio/transcriptions``
endpoint and sends no session/meeting id. A persistent per-meeting Realtime WS
session therefore cannot be keyed from Vexa's calls, and opening a fresh socket
per ~3s chunk would be strictly worse than the REST path.

The gpt-4o-transcribe family is fully served over REST (azure_openai_rest), so
this provider is a documented placeholder retained for capability-table
completeness and potential future whole-recording/batch use. It raises clearly
if a model is ever mapped to ``azure_openai_realtime``.
"""
from __future__ import annotations

from .base import ProviderError, TranscriptionProvider


class AzureRealtimeProvider(TranscriptionProvider):
    def __init__(self, model_id, capability, settings, http_client):
        self.model_id = model_id
        self.capability = capability

    async def transcribe(self, audio, **kwargs):  # noqa: D401
        raise ProviderError(
            "azure_openai_realtime is not used for Vexa's per-chunk REST hook; "
            "select the REST variant instead (e.g. gpt-4o-transcribe).",
            status_code=501,
        )
