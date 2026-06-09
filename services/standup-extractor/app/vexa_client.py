"""Fetch a meeting's transcript from Vexa via the internal collector endpoint.

Uses ``GET /internal/transcripts/{meeting_id}`` (meeting-api collector), which is
keyed by the internal meeting id (exactly what the POST_MEETING_HOOKS payload
carries) and gated by the ``X-Internal-Secret`` header. The public
``/transcripts/{platform}/{native_meeting_id}`` route is NOT usable here because
the hook payload does not include native_meeting_id.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

logger = logging.getLogger("standup_extractor.vexa_client")


class VexaClient:
    def __init__(self, base_url: str, internal_secret: str, http: httpx.AsyncClient,
                 timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.internal_secret = internal_secret
        self.http = http
        self.timeout = timeout

    async def fetch_segments(self, meeting_id: int) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/internal/transcripts/{meeting_id}"
        resp = await self.http.get(
            url,
            headers={"X-Internal-Secret": self.internal_secret},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        # Endpoint returns a JSON list of TranscriptionSegment.
        return data if isinstance(data, list) else (data.get("segments") or [])
