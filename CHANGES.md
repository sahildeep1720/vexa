# CHANGES — Azure transcription adapter + standup-extractor

This integration is **additive** and kept separate from Vexa core so upstream
merges stay painless.

## Vexa core files modified

**None.** No file under `services/` (other than the two new service directories),
`deploy/`, or any existing Vexa module was edited.

Integration is achieved entirely through Vexa's existing hooks:

| Hook | Mechanism | Where |
|------|-----------|-------|
| Transcription backend | `TRANSCRIPTION_SERVICE_URL` / `TRANSCRIPTION_SERVICE_TOKEN` env (read by meeting-api, passed to each bot) | set in `.env` |
| Meeting-end trigger | `POST_MEETING_HOOKS` env (internal post-meeting hook fired by `meeting-api/post_meeting.py`) | set in `.env` |
| Transcript fetch | `GET /internal/transcripts/{meeting_id}` with `X-Internal-Secret` (existing internal endpoint) | called by standup-extractor |

## New files

- `services/azure-transcriber/` — OpenAI-compatible (`POST /v1/audio/transcriptions`)
  facade over Azure transcription models. Drop-in for `services/transcription-service`.
- `services/standup-extractor/` — FastAPI service triggered by `POST_MEETING_HOOKS`;
  extracts per-person standup (Azure GPT-5.5, strict JSON) → stubbed Kanban client.
- `docker-compose.azure.yml` — overlay that adds both services to the `vexa` network.
- `.env.azure.example` — every new env var, commented; append to `.env`.

## How to run

```bash
cp deploy/env-example .env            # if you don't have one yet
cat .env.azure.example >> .env        # then fill in the Azure values
# NOTE: --env-file is required. Compose's project dir is the FIRST -f file's
# directory (deploy/compose), so it would otherwise look for .env there, not at
# the repo root. This mirrors Vexa's own Makefile (--env-file $(ROOT)/.env).
docker compose --env-file .env \
  -f deploy/compose/docker-compose.yml -f docker-compose.azure.yml up -d --pull=missing
```

## Default backend: OpenRouter (branch `feat/openrouter`)

Both services default to **OpenRouter** (one `OPENROUTER_API_KEY` for both); Azure
remains selectable as a fallback. No Azure account is required.

- Transcription: `TRANSCRIBER_MODEL=openrouter` → OpenRouter `POST /api/v1/audio/transcriptions`
  (JSON+base64, namespaced slug `openai/gpt-4o-transcribe`). **Tradeoff:** OpenRouter STT
  returns **text only — no word/segment timestamps**. The adapter synthesizes one full-chunk
  segment, so speaker attribution is **chunk-level** (fine for Google Meet's per-speaker
  capture; coarser for Teams' mixed audio). For word-level splitting, set
  `TRANSCRIBER_MODEL=gpt-4o-transcribe` (Azure) or point at a local Whisper.
- Standup LLM: `MODEL_MODE=openrouter`, `openai/gpt-5.5`, `response_format=json_schema`
  (strict) + `provider:{require_parameters:true}` so OpenRouter only routes to a
  structured-output-capable provider. Reasoning model → `max_tokens`, no `temperature`.

## Notable design decisions (see services/*/README.md and the plan for rationale)

- Vexa's transcriber transport is per-chunk **HTTP `/v1/audio/transcriptions`**
  (OpenAI verbose_json), **not** a WhisperLive WebSocket. The adapter implements that
  exact inbound contract regardless of backend.
- Vexa does **its own speaker attribution** from Whisper word timestamps; the
  transcriber's `speaker` field is unused. Backends that omit word timestamps (OpenRouter,
  Azure diarize) therefore reduce attribution to segment/chunk granularity.
- The adapter is multi-backend via a provider abstraction + capability table; switching
  backend is a one-line `TRANSCRIBER_MODEL` / `MODEL_MODE` env change.
