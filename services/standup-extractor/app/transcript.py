"""Turn Vexa transcript segments into a readable, speaker-attributed transcript.

Vexa's internal endpoint returns segments serialized with field aliases
``start``/``end`` (Pydantic alias of start_time/end_time); we read both forms
defensively. Consecutive segments by the same speaker are merged into blocks, and
speaker labels are mapped to real names via TEAM_ROSTER.
"""
from __future__ import annotations

from typing import Any, Dict, List

UNKNOWN = "Unknown speaker"


def _start(seg: Dict[str, Any]) -> float:
    v = seg.get("start", seg.get("start_time"))
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _speaker(seg: Dict[str, Any]) -> str:
    sp = seg.get("speaker")
    return sp if sp else UNKNOWN


def group_by_speaker(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge consecutive same-speaker segments into blocks, ordered by start time."""
    ordered = sorted(segments, key=_start)
    blocks: List[Dict[str, Any]] = []
    for seg in ordered:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = _speaker(seg)
        if blocks and blocks[-1]["speaker"] == speaker:
            blocks[-1]["text"] += " " + text
        else:
            blocks.append({"speaker": speaker, "text": text})
    return blocks


def apply_roster(speaker: str, roster: Dict[str, str]) -> str:
    return roster.get(speaker, speaker)


def render_transcript(blocks: List[Dict[str, Any]], roster: Dict[str, str]) -> str:
    return "\n".join(f"{apply_roster(b['speaker'], roster)}: {b['text']}" for b in blocks)


def participant_names(blocks: List[Dict[str, Any]], roster: Dict[str, str]) -> List[str]:
    seen: List[str] = []
    for b in blocks:
        name = apply_roster(b["speaker"], roster)
        if name not in seen:
            seen.append(name)
    return seen
