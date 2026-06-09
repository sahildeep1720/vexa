"""Kanban API client — STUB / ADAPTER.

================================ ADAPTER BOUNDARY ================================
This is the ONE place to wire your real Kanban API. The push() method currently
logs the payload it would send and, if KANBAN_API_URL is set, makes a best-effort
generic POST. Replace the body of push() with your real endpoints, auth, and
payload mapping.

TODO(you): set the real base URL, auth scheme, per-card endpoint, and field mapping.
=================================================================================
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("standup_extractor.kanban")


class KanbanClient:
    def __init__(self, base_url: Optional[str], api_key: Optional[str],
                 http: httpx.AsyncClient, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.api_key = api_key
        self.http = http
        self.timeout = timeout

    async def push(self, meeting_id: int, people: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Push extracted standup updates to the Kanban board.

        `people` is a list of {name, yesterday[], today[], blockers[]}.
        """
        payload = {"meeting_id": meeting_id, "people": people}

        if not self.base_url:
            # No endpoint configured yet — log what we *would* send.
            logger.info("[kanban-stub] would POST %d person update(s) for meeting %s: %s",
                        len(people), meeting_id, payload)
            return {"status": "stubbed", "pushed": len(people)}

        # TODO(you): replace with the real Kanban contract (endpoint/auth/shape).
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = await self.http.post(f"{self.base_url}/standups", json=payload,
                                        headers=headers, timeout=self.timeout)
            logger.info("[kanban] POST /standups -> %s", resp.status_code)
            return {"status": "sent", "status_code": resp.status_code}
        except httpx.HTTPError as e:
            logger.error("[kanban] push failed: %s", e)
            return {"status": "error", "error": str(e)}
