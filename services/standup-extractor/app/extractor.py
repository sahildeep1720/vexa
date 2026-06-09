"""Extract per-person standup data (yesterday/today/blockers) as strict JSON.

Default backend is Azure OpenAI ``gpt-5.5`` — a REASONING model, so we send
``max_completion_tokens`` and DO NOT send ``temperature``. Structured Outputs
(``response_format=json_schema``, strict) guarantees schema adherence. A
``MODEL_MODE=openai_compatible`` path targets a LiteLLM-style proxy.
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
    "category, return an empty list for it. Omit participants who did not give an update."
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


class StandupExtractor:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http

    async def extract(self, transcript_text: str, participants: List[str]) -> Dict[str, Any]:
        messages = build_messages(transcript_text, participants)
        mode = self.settings.model_mode
        if mode == "openrouter":
            content = await self._call_openrouter(messages)
        elif mode == "openai_compatible":
            content = await self._call_openai_compatible(messages)
        else:
            content = await self._call_azure(messages)
        return _parse_json(content)

    async def _call_openrouter(self, messages: List[Dict[str, str]]) -> str:
        s = self.settings
        if not s.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        url = f"{s.openrouter_base_url.rstrip('/')}/chat/completions"
        body: Dict[str, Any] = {
            "model": s.openrouter_model,
            "messages": messages,
            "response_format": response_format(),
            # gpt-5.5's OpenRouter endpoint advertises max_tokens.
            "max_tokens": s.max_completion_tokens,
        }
        if s.openrouter_require_parameters:
            # Only route to a provider that honors response_format, so strict JSON
            # isn't silently dropped (OpenRouter default require_parameters is false).
            body["provider"] = {"require_parameters": True}
        if not s.reasoning_model and s.llm_temperature is not None:
            body["temperature"] = s.llm_temperature  # reasoning models reject temperature
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {s.openrouter_api_key}"}
        if s.openrouter_referer:
            headers["HTTP-Referer"] = s.openrouter_referer
        if s.openrouter_title:
            headers["X-Title"] = s.openrouter_title
        resp = await self.http.post(url, headers=headers, json=body, timeout=s.request_timeout_s)
        resp.raise_for_status()
        return _content_from_chat(resp.json())

    async def _call_azure(self, messages: List[Dict[str, str]]) -> str:
        s = self.settings
        if not s.azure_openai_endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT is not configured")
        url = (f"{s.azure_openai_endpoint.rstrip('/')}/openai/deployments/"
               f"{s.azure_openai_deployment}/chat/completions"
               f"?api-version={s.azure_openai_api_version}")
        body: Dict[str, Any] = {
            "messages": messages,
            "response_format": response_format(),
            "max_completion_tokens": s.max_completion_tokens,  # reasoning models reject max_tokens
        }
        if not s.reasoning_model and s.llm_temperature is not None:
            body["temperature"] = s.llm_temperature
        headers = {"Content-Type": "application/json"}
        if s.azure_use_aad:
            headers["Authorization"] = f"Bearer {await _aad_token()}"
        else:
            if not s.azure_openai_api_key:
                raise RuntimeError("AZURE_OPENAI_API_KEY is not configured")
            headers["api-key"] = s.azure_openai_api_key

        resp = await self.http.post(url, headers=headers, json=body, timeout=s.request_timeout_s)
        resp.raise_for_status()
        return _content_from_chat(resp.json())

    async def _call_openai_compatible(self, messages: List[Dict[str, str]]) -> str:
        s = self.settings
        if not s.openai_compat_base_url:
            raise RuntimeError("OPENAI_COMPAT_BASE_URL is not configured")
        url = f"{s.openai_compat_base_url.rstrip('/')}/chat/completions"
        body: Dict[str, Any] = {
            "model": s.openai_compat_model,
            "messages": messages,
            "response_format": response_format(),
            "max_tokens": s.max_completion_tokens,
        }
        if s.llm_temperature is not None:
            body["temperature"] = s.llm_temperature
        headers = {"Content-Type": "application/json"}
        if s.openai_compat_api_key:
            headers["Authorization"] = f"Bearer {s.openai_compat_api_key}"
        resp = await self.http.post(url, headers=headers, json=body, timeout=s.request_timeout_s)
        resp.raise_for_status()
        return _content_from_chat(resp.json())


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


async def _aad_token() -> str:
    try:
        from azure.identity import DefaultAzureCredential  # optional dependency
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("AZURE_USE_AAD=true but azure-identity is not installed") from e
    import asyncio
    cred = DefaultAzureCredential()
    token = await asyncio.to_thread(cred.get_token, "https://ai.azure.com/.default")
    return token.token
