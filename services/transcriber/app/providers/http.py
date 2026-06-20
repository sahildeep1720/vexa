"""Shared HTTP helper: POST with bounded retry on 429/503 + network errors."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

import httpx

from .base import ProviderError

logger = logging.getLogger("transcriber.http")


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
                # httpx 0.28 raises "Attempted to send a sync request with an
                # AsyncClient instance" when `data` (form fields) and `files` are
                # passed together. Merge the form fields into the files list as
                # (name, (None, value)) parts — a pure multipart that works async.
                parts = list(files.items()) if files else []
                for k, v in (data or []):
                    parts.append((k, (None, v)))
                resp = await http.post(url, headers=headers, files=parts,
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
            raise ProviderError(f"{label}: upstream returned {resp.status_code}: {resp.text[:500]}",
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
