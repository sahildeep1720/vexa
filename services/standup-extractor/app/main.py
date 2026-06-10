"""standup-extractor — turn a finished Vexa meeting into per-person standup cards.

Flow: Vexa POST_MEETING_HOOKS delivers a `meeting.completed` envelope -> we ACK
fast (202) -> in the background we fetch the transcript from meeting-api's internal
endpoint, group it by speaker, extract yesterday/today/blockers with OpenRouter
gpt-5.5 (strict JSON, in English), and push to the (stubbed) Kanban API. Idempotent
on event_id.
"""
from __future__ import annotations

import logging
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Dict

import httpx
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

from .config import load_settings
from .extractor import StandupExtractor
from .kanban_client import KanbanClient
from .schema import extract_meeting_id, meeting_field
from .transcript import group_by_speaker, participant_names, render_transcript
from .vexa_client import VexaClient

settings = load_settings()
logging.basicConfig(
    level=getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("standup_extractor")

_MAX_SEEN = 2048


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        timeout=settings.request_timeout_s,
    )
    app.state.vexa = VexaClient(settings.meeting_api_internal_url, settings.internal_api_secret,
                                app.state.http)
    app.state.extractor = StandupExtractor(settings, app.state.http)
    app.state.kanban = KanbanClient(settings.kanban_api_url, settings.kanban_api_key, app.state.http)
    app.state.seen_events = deque(maxlen=_MAX_SEEN)
    app.state.seen_set = set()
    logger.info("standup-extractor ready: model=%s", settings.openrouter_model)
    yield
    await app.state.http.aclose()


app = FastAPI(title="standup-extractor", lifespan=lifespan)


def _already_processed(app: FastAPI, event_id: str) -> bool:
    if event_id in app.state.seen_set:
        return True
    if len(app.state.seen_events) == app.state.seen_events.maxlen:
        oldest = app.state.seen_events[0]
        app.state.seen_set.discard(oldest)
    app.state.seen_events.append(event_id)
    app.state.seen_set.add(event_id)
    return False


@app.get("/health")
async def health():
    return {"status": "healthy", "model": settings.openrouter_model}


@app.post("/hooks/meeting-completed")
async def meeting_completed(request: Request, background: BackgroundTasks):
    try:
        envelope: Dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"detail": "invalid JSON"}, status_code=400)

    event_type = envelope.get("event_type")
    if event_type != "meeting.completed":
        # Accept-and-ignore other events so Vexa doesn't retry them.
        return JSONResponse({"status": "ignored", "event_type": event_type}, status_code=202)

    meeting_id = extract_meeting_id(envelope)
    if meeting_id is None:
        return JSONResponse({"detail": "missing data.meeting.id"}, status_code=400)

    event_id = envelope.get("event_id") or f"meeting:{meeting_id}"
    if _already_processed(app, event_id):
        logger.info("duplicate event %s (meeting %s); skipping", event_id, meeting_id)
        return JSONResponse({"status": "duplicate", "meeting_id": meeting_id}, status_code=202)

    background.add_task(_process_meeting, meeting_id, envelope)
    return JSONResponse({"status": "accepted", "meeting_id": meeting_id}, status_code=202)


async def _process_meeting(meeting_id: int, envelope: Dict[str, Any]) -> None:
    platform = meeting_field(envelope, "platform")
    logger.info("processing meeting %s (platform=%s)", meeting_id, platform)
    try:
        segments = await app.state.vexa.fetch_segments(meeting_id)
        logger.info("meeting %s: fetched %d segment(s)", meeting_id, len(segments))
        blocks = group_by_speaker(segments)
        if not blocks:
            logger.info("meeting %s: empty transcript; nothing to extract", meeting_id)
            return
        transcript_text = render_transcript(blocks, settings.team_roster)
        participants = participant_names(blocks, settings.team_roster)
        logger.info("meeting %s: %d participant(s): %s", meeting_id, len(participants), participants)

        result = await app.state.extractor.extract(transcript_text, participants)
        people = result.get("people", [])
        logger.info("meeting %s: extracted standup for %d person(s)", meeting_id, len(people))

        push_result = await app.state.kanban.push(meeting_id, people)
        logger.info("meeting %s: kanban push -> %s", meeting_id, push_result)
    except httpx.HTTPStatusError as e:
        logger.error("meeting %s: HTTP error: %s -> %s", meeting_id, e.request.url,
                     e.response.status_code if e.response else "?")
    except Exception as e:
        logger.exception("meeting %s: processing failed: %s", meeting_id, e)
