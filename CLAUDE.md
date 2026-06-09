# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 0. Release stage machine — orient BEFORE acting

This repo runs under a **strict stage state machine** (`tests3/`). It is a behavioral
contract that OVERRIDES default behavior — follow it exactly.

**First action, every session:**

```bash
make stage          # = python3 tests3/lib/stage.py probe — prints current stage + legal next + objective
```

Then read the contract for the current stage at `tests3/stages/NN-<name>.md` (objective,
inputs, outputs, exit condition, and a **may NOT** list) before taking any action.

- If the user asks for something on a stage's `may NOT` list, **refuse** with a stage-aware
  message and the legal transition path, e.g. *"Currently in `plan`; editing code is
  forbidden. Advance via `develop` first."*
- Map requests to stages: *debug/fix/write code* → `develop` (entered from `plan`/`triage`);
  *run tests/check the gate* → `validate` (from `deploy`); *classify failures* → `triage`;
  *sign off* → `human`; *ship/merge* → `ship`; *start a release/groom* → `groom`.
- **You are NOT the user.** Never set `plan-approval.yaml` / `human-approval.yaml` (or any
  exit condition) to `approved: true` unless the user says so in the current turn. You prepare
  approval material; humans grant approval.
- The release runs three nested loops: **INNER** validate→triage→develop→deploy→validate
  (cheap, many/day); **MIDDLE** validate(green)→human→ship (bounded human attention);
  **OUTER** ship→market→issues→groom (real users). Drifting between stages breaks the
  Registry's regression guarantee. Full model: `tests3/README.md`.

> Note: a fresh clone is **uninitialised** (no `tests3/.current-stage`); the machine engages
> only inside a release cycle started via `make release-groom`. Purely additive work that
> does not touch DoD-tracked core (see §3) proceeds as a normal feature add.

---

## 1. Common commands

**Run the stack** (from repo root; both prompt for a transcription token on first run):

```bash
make all            # full compose stack, each service a separate container (alias: make up)
make lite           # single-container deploy (Vexa Lite)
make build          # build all images from source
make down           # stop the compose stack
make -C deploy/compose ps|logs        # status / tail logs of the compose stack
```

**Tests / checks:**

```bash
make smoke          # all static + health + contract checks, no meetings (~30s)
make test           # resolve changed files -> run only affected tests
make what-changed   # dry-run: show which tests `make test` would run
make full           # run everything

# tests3 is the layered test runner — run a single check by target:
make -C tests3 health        # service endpoints respond (5s)
make -C tests3 contracts     # API behavior (15s)
make -C tests3 webhooks      # webhook envelope/HMAC (10s)
make -C tests3 meeting-tts   # full live meeting: join -> TTS -> transcript (~10min)
# Live meeting targets need env like MEETING_URL / TEAMS_MEETING_URL (see tests3/Makefile).

# Per-service Python unit tests (pytest) — run in the service dir with its deps:
cd services/meeting-api && pytest tests/ -v
cd services/meeting-api && pytest tests/test_webhooks.py::test_name -v   # single test
```

**Release pipeline** (`make release-*`): each target maps to a stage in §0 —
`release-groom`, `release-plan`, `release-provision`, `release-deploy`, `release-validate`,
`release-triage`, `release-human`, `release-ship`. Do not invoke these to "just run code";
obey the stage.

---

## 2. Architecture — the big picture

Vexa is a set of microservices (mostly FastAPI/Python; dashboard is Next.js) run by
docker-compose, sharing **Postgres**, **Redis**, and **MinIO/S3** on the `vexa` docker
network. Services communicate via REST + Redis (streams/pub-sub), not tight coupling.
Host ports are remapped (gateway `8056`, dashboard `3001`, postgres `5458`, …) but services
reach each other on internal names/ports (`api-gateway:8000`, `meeting-api:8080`,
`transcription-service:8083`, `runtime-api:8090`). Map: `services/README.md`.

**Layering:** `api-gateway` (auth/routing) → `admin-api` (users/tokens), `meeting-api`
(meeting domain), `agent-api` (chat/TTS) → `runtime-api` is the infrastructure layer that
**spawns containers** (`vexa-bot`, agents) via Docker / K8s / process backends.

**Transcription pipeline — the most important flow, and counter-intuitive (verify in code,
not from old docs):**

1. `runtime-api` spawns a **`vexa-bot`** container (TypeScript/Playwright) that joins the
   meeting and captures per-speaker audio (16 kHz mono PCM). The **real-time transcription
   pipeline runs INSIDE the bot** (v0.10 refactor), not as an external service.
2. The bot POSTs **discrete WAV chunks over HTTP** to an **OpenAI-compatible REST endpoint
   `POST /v1/audio/transcriptions`** (returns `verbose_json`). It is **not** a WhisperLive
   WebSocket. The backend is selected purely by the **`TRANSCRIPTION_SERVICE_URL`** env
   (+ `TRANSCRIPTION_SERVICE_TOKEN`) — this is the integration/swap hook.
   (`services/vexa-bot/core/src/services/transcription-client.ts`,
   `services/transcription-service/main.py`.)
3. The transcriber is pure speech-to-text and returns **no speaker labels**. The **bot does
   its own speaker attribution** from Whisper word timestamps + platform speaker boundaries,
   then publishes attributed segments to **Redis streams** (`transcription_segments`) + pub-sub.
4. The **collector is built into `meeting-api`** (`meeting_api/collector/`): it consumes the
   streams and persists segments to Postgres, served via REST
   `GET /transcripts/{platform}/{native_meeting_id}` (and internal `/internal/transcripts/{id}`
   gated by `X-Internal-Secret`) and a WebSocket (`api-gateway /ws`, fanning in Redis
   `tc:meeting:{id}:mutable` etc.).

**Meeting-end hooks:** `meeting-api` emits per-user webhooks (`meeting.completed` /
`meeting.status_change`, HMAC-signed, SSRF-validated so they can't target internal hosts) and
fires internal **`POST_MEETING_HOOKS`** (comma-separated URLs) — the latter is the trigger for
in-compose post-meeting services. (`meeting_api/webhooks.py`, `post_meeting.py`,
`webhook_delivery.py`.)

**Identity:** a meeting has an internal `id` and an external `(platform, native_meeting_id)`;
a `MeetingToken` JWT carries both through the pipeline.

**Deploy modes:** `deploy/compose/` (canonical compose + its own Makefile), `deploy/lite/`
(single container), `deploy/helm/` (K8s). Self-hosted GPU transcription is a separate stack in
`services/transcription-service/` enabled with `LOCAL_TRANSCRIPTION=true`.

---

## 3. The tests3 system (Registry + DoD)

`tests3/` is both the **test runner** (layered targets: docs/locks/env/health/contracts →
smoke, then dashboard/containers/browser/meeting tiers) and the **release governance** (the
stage machine in §0). `tests3/registry.yaml` + per-service/feature **DoD tables** (in each
README) encode the regression guarantee. `make -C tests3 validate-{lite,compose,helm}` runs a
mode's matrix and writes JSON reports; `make -C tests3 report` aggregates them. Reports live in
`tests3/reports/`, release state in `tests3/releases/<id>/`.

---

## 4. Azure overlay (local addition, kept separate from core)

A `docker-compose.azure.yml` overlay adds two services that integrate **only via env + the
hooks above — zero edits to Vexa core** (see `CHANGES.md`):

- `services/azure-transcriber/` — OpenAI-compatible (`/v1/audio/transcriptions`) facade;
  multi-backend via `TRANSCRIBER_MODEL` (capability table in `app/providers/`). On branch
  `feat/openrouter` the **default is `openrouter`** (text-only → synthesized single segment,
  no word timestamps); Azure `gpt-4o-transcribe` etc. remain selectable. Drop-in for
  `transcription-service`; wired by `TRANSCRIPTION_SERVICE_URL` in `.env`.
- `services/standup-extractor/` — FastAPI service triggered by `POST_MEETING_HOOKS`; pulls the
  transcript via the internal endpoint, extracts per-person standup JSON via `MODEL_MODE`
  (`openrouter` default → `openai/gpt-5.5` strict `json_schema`; `azure` / `openai_compatible`
  alternates), pushes to a stubbed Kanban client.

```bash
# --env-file is required: compose reads .env from the first -f file's dir
# (deploy/compose), not the repo root — mirrors Vexa's Makefile.
docker compose --env-file .env \
  -f deploy/compose/docker-compose.yml -f docker-compose.azure.yml up -d --pull=missing
cd services/azure-transcriber && pytest tests/ -v   # unit tests (no Azure creds needed)
```

New env vars are documented in `.env.azure.example`; design rationale in each service README.
