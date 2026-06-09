"""Schemas: the meeting-completed hook envelope + the strict standup JSON schema.

The hook envelope is what Vexa's POST_MEETING_HOOKS delivers
(meeting_api/webhook_delivery.build_envelope):
  {event_id, event_type, api_version, created_at, data: {meeting: {...}}}
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def extract_meeting_id(envelope: Dict[str, Any]) -> Optional[int]:
    meeting = (envelope.get("data") or {}).get("meeting") or {}
    mid = meeting.get("id")
    try:
        return int(mid) if mid is not None else None
    except (TypeError, ValueError):
        return None


def meeting_field(envelope: Dict[str, Any], key: str) -> Any:
    return ((envelope.get("data") or {}).get("meeting") or {}).get(key)


# Azure OpenAI Structured Outputs rules: every property in `required`,
# additionalProperties:false on every object. Per-person yesterday/today/blockers.
STANDUP_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["people"],
    "properties": {
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "yesterday", "today", "blockers"],
                "properties": {
                    "name": {"type": "string", "description": "Speaker's real name"},
                    "yesterday": {"type": "array", "items": {"type": "string"},
                                  "description": "What they did since the last standup"},
                    "today": {"type": "array", "items": {"type": "string"},
                              "description": "What they plan to do today"},
                    "blockers": {"type": "array", "items": {"type": "string"},
                                 "description": "Blockers / impediments they mentioned"},
                },
            },
        }
    },
}


def response_format() -> Dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "standup_extraction",
            "strict": True,
            "schema": STANDUP_JSON_SCHEMA,
        },
    }
