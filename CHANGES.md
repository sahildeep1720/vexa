# CHANGES — OpenRouter transcription adapter + standup-extractor

This integration is **additive** and kept separate from Vexa core so upstream
merges stay painless.

## Vexa core files modified

**None.**\* No file under `services/` (other than the two new service directories),
`deploy/`, or any existing Vexa module was edited.

\* The only nuance: the **scheduler/cron** feature needs `croniter`, which the
published `vexaai/runtime-api` image does not ship. Rather than edit any core file,
the overlay runs a **derived image** built from `ops/runtime-api-cron.Dockerfile`
(`FROM vexaai/runtime-api` + `pip install croniter`). Zero core files are touched —
only an overlay-owned Dockerfile that extends the upstream image.

Integration is achieved entirely through Vexa's existing hooks:

| Hook | Mechanism | Where |
|------|-----------|-------|
| Transcription backend | `TRANSCRIPTION_SERVICE_URL` / `TRANSCRIPTION_SERVICE_TOKEN` env (read by meeting-api, passed to each bot) | set in `.env` |
| Meeting-end trigger | `POST_MEETING_HOOKS` env (internal post-meeting hook fired by `meeting-api/post_meeting.py`) | set in `.env` |
| Transcript fetch | `GET /internal/transcripts/{meeting_id}` with `X-Internal-Secret` (existing internal endpoint) | called by standup-extractor |

## New files

- `services/transcriber/` — OpenAI-compatible (`POST /v1/audio/transcriptions`) facade over OpenRouter STT. Drop-in for `services/transcription-service`.
- `services/standup-extractor/` — FastAPI service triggered by `POST_MEETING_HOOKS`; extracts per-person standup (OpenRouter `gpt-5.5`, strict JSON, English output) → stubbed Kanban client.
- `docker-compose.openrouter.yml` — overlay that adds both services to the `vexa` network.
- `.env.openrouter.example` — every new env var, commented; append to `.env`.
- `ops/stack.sh` — single entrypoint for bringing the overlay up/down (`up`, `up-lean`, `down`, …); wraps the compose invocation so no raw `docker compose` is needed.
- `ops/schedule-standup.sh` — registers a daily auto-join cron with `runtime-api`'s scheduler (e.g. `add <meet-id> --time 10:30`).
- `ops/runtime-api-cron.Dockerfile` — derived image `FROM vexaai/runtime-api` + `pip install croniter`, so the scheduler has its one missing dep without editing core.
- `ops/VM-RUNBOOK.md` — operator runbook for deploying and running the overlay on a VM.

## How to run

```bash
cp deploy/env-example .env             # if you don't have one yet
cat .env.openrouter.example >> .env    # then fill in the OpenRouter values

ops/stack.sh up-lean   # lean profile: 11 containers (drops dashboard + mcp; keeps tts-service + recordings)
ops/stack.sh up        # full profile: every service
ops/stack.sh down      # stop the stack
```

`ops/stack.sh` wraps the compose invocation (correct `--env-file`, both `-f` files,
the derived runtime-api-cron image), so you never call `docker compose` by hand.

## Default backend: OpenRouter (branch `feat/openrouter`)

Both services run on **OpenRouter** (one `OPENROUTER_API_KEY` for both). No Azure
account or other provider is required. `OPENROUTER_BASE_URL` is configurable, so any
OpenAI-compatible proxy can stand in for OpenRouter without code changes.

- Transcription: OpenRouter `POST /api/v1/audio/transcriptions` (JSON+base64,
  namespaced slug `openai/gpt-4o-transcribe`). **Tradeoff:** OpenRouter STT returns
  **text only — no word/segment timestamps**. The adapter synthesizes one full-chunk
  segment, so speaker attribution is **chunk-level** (fine for Google Meet's
  per-speaker capture; coarser for Teams' mixed audio). For word-level splitting,
  point `TRANSCRIPTION_SERVICE_URL` at a local Whisper instead.
- Standup LLM: `openai/gpt-5.5`, `response_format=json_schema` (strict) +
  `provider:{require_parameters:true}` so OpenRouter only routes to a
  structured-output-capable provider. Reasoning model → `max_tokens`, no `temperature`.

## Notable design decisions (see services/*/README.md and the plan for rationale)

- **OpenRouter-only adapter.** All Azure code was stripped; the adapter speaks one
  backend (OpenRouter / any OpenAI-compatible proxy via `OPENROUTER_BASE_URL`). This
  keeps the surface small and removes per-provider capability branching.
- **Chunk granularity is the central tradeoff.** Vexa's transcriber transport is
  per-chunk **HTTP `/v1/audio/transcriptions`** (OpenAI verbose_json), **not** a
  WhisperLive WebSocket; the adapter implements that exact inbound contract. Vexa does
  **its own speaker attribution** from word timestamps, and the transcriber's `speaker`
  field is unused. Because OpenRouter STT returns no word timestamps, attribution drops
  to segment/chunk granularity — acceptable for Meet's per-speaker audio, coarser for
  mixed-audio platforms.
- **Standup output is always English.** Hindi/Hinglish input is translated to English in
  the extracted JSON; **person names are never translated** (they pass through verbatim).
- **Lean profile.** `ops/stack.sh up-lean` drops the dashboard and mcp services while
  keeping `tts-service` and `recordings`, landing at 11 containers — enough to run live
  meetings + standup extraction on a small VM without the UI/agent surface.
- **Daily auto-join.** `runtime-api`'s scheduler cron handles recurring joins; register
  one with `ops/schedule-standup.sh add <meet-id> --time 10:30`. The scheduler needs
  `croniter`, supplied by the derived `runtime-api-cron` image (see the asterisk above).
