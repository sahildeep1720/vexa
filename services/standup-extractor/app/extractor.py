"""Extract per-person standup data (yesterday/today/blockers) as strict JSON.

The backend is OpenRouter (``openai/gpt-5.5`` by default) — a REASONING model, so
we send ``max_tokens`` and DO NOT send ``temperature``. Structured Outputs
(``response_format=json_schema``, strict) guarantees schema adherence, and
``provider:{require_parameters:true}`` keeps OpenRouter from routing to a provider
that silently drops it.

``OPENROUTER_BASE_URL`` accepts any OpenAI-compatible ``/chat/completions`` proxy
(e.g. a LiteLLM gateway); set ``OPENROUTER_REQUIRE_PARAMETERS=false`` for proxies
that reject the ``provider`` field.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

import httpx

from .config import Settings
from .schema import response_format

logger = logging.getLogger("standup_extractor.extractor")

_SYSTEM = (
    "You extract daily-standup updates from a meeting transcript. "
    "For each participant who spoke, produce their standup as three lists: "
    "what they did since the last standup (yesterday), what they plan to do (today), "
    "and any blockers/impediments. Use ONLY information stated in the transcript — "
    "never invent items. Attribute statements to the speaker who made them, using the "
    "names as they appear in the transcript. If a participant did not mention a "
    "category, return an empty list for it. Omit participants who did not give an update. "
    "The meeting may be spoken in Hindi, English, or mixed Hinglish (including Devanagari "
    "script). ALWAYS write the standup items (yesterday/today/blockers) in clear, natural "
    "ENGLISH — translate faithfully without adding or dropping information. NEVER translate "
    "or transliterate speaker names: keep each person's name exactly as it appears in the "
    "transcript. Keep technical terms, product names, library names, and ticket IDs verbatim. "
    "Handle code-switching naturally."
)


def build_messages(transcript_text: str, participants: List[str]) -> List[Dict[str, str]]:
    roster_line = (
        f"Known participants: {', '.join(participants)}.\n\n" if participants else ""
    )
    user = (
        f"{roster_line}Transcript:\n\n{transcript_text}\n\n"
        "Return the standup updates as JSON matching the provided schema."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]


def build_headers(settings: Settings) -> Dict[str, str]:
    """Auth + content headers for the OpenRouter (OpenAI-compatible) chat call.

    Adds OpenRouter's optional app-attribution headers (HTTP-Referer / X-Title)
    only when configured; harmless to omit against a plain proxy.
    """
    s = settings
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {s.openrouter_api_key}",
    }
    if s.openrouter_referer:
        headers["HTTP-Referer"] = s.openrouter_referer
    if s.openrouter_title:
        headers["X-Title"] = s.openrouter_title
    return headers


def build_request_body(settings: Settings, messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """Chat-completions body with strict structured outputs.

    gpt-5.5's OpenRouter endpoint advertises ``max_tokens``. The ``provider`` block
    is sent only when ``openrouter_require_parameters`` is on (some proxies reject
    it), and ``temperature`` only for non-reasoning models that set one.
    """
    s = settings
    body: Dict[str, Any] = {
        "model": s.openrouter_model,
        "messages": messages,
        "response_format": response_format(),
        "max_tokens": s.max_completion_tokens,
    }
    if s.openrouter_require_parameters:
        # Only route to a provider that honors response_format, so strict JSON
        # isn't silently dropped (OpenRouter default require_parameters is false).
        body["provider"] = {"require_parameters": True}
    if not s.reasoning_model and s.llm_temperature is not None:
        body["temperature"] = s.llm_temperature  # reasoning models reject temperature
    return body


class StandupExtractor:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http

    async def extract(self, transcript_text: str, participants: List[str]) -> Dict[str, Any]:
        s = self.settings
        if not s.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        messages = build_messages(transcript_text, participants)
        url = f"{s.openrouter_base_url.rstrip('/')}/chat/completions"
        headers = build_headers(s)
        body = build_request_body(s, messages)
        resp = await self.http.post(url, headers=headers, json=body, timeout=s.request_timeout_s)
        resp.raise_for_status()
        return _parse_json(_content_from_chat(resp.json()))


def _content_from_chat(payload: Dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM returned no choices: {str(payload)[:300]}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if content is None:
        raise RuntimeError(f"LLM returned no content (refusal?): {str(message)[:300]}")
    return content


def _parse_json(content: str) -> Dict[str, Any]:
    try:
        data = json.loads(content)
    except (ValueError, TypeError) as e:
        raise RuntimeError(f"LLM output was not valid JSON: {e}: {content[:300]}")
    if not isinstance(data, dict) or "people" not in data:
        raise RuntimeError(f"LLM output missing 'people': {str(data)[:300]}")
    return data
