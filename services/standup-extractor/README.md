# standup-extractor

A FastAPI service that turns each finished Vexa meeting into per-person standup
cards (yesterday / today / blockers) and pushes them to a Kanban API.

## Flow

```
Vexa meeting ends
  -> meeting-api fires POST_MEETING_HOOKS  ("meeting.completed" envelope)
  -> POST /hooks/meeting-completed          (we ACK 202 immediately)
  -> [background]
       GET meeting-api:8080/internal/transcripts/{id}   (X-Internal-Secret)
       group segments by speaker + map via TEAM_ROSTER
       Azure GPT-5.5 strict-JSON extraction (yesterday/today/blockers)
       kanban_client.push(...)              (STUB — see app/kanban_client.py)
```

Why the **internal** transcript endpoint: the `POST_MEETING_HOOKS` payload carries
the internal `meeting.id` (and `user_email`) but **not** `native_meeting_id`, so the
public `/transcripts/{platform}/{native_meeting_id}` route can't be used. The internal
endpoint is keyed by id and gated by `X-Internal-Secret` (= Vexa's `INTERNAL_API_SECRET`).

Why `POST_MEETING_HOOKS` (not per-user webhooks): Vexa SSRF-validates per-user webhook
URLs and **blocks internal Docker hostnames**, so a per-user webhook can't reach this
in-compose service. `POST_MEETING_HOOKS` is the operator/internal hook and is the right
trigger.

## LLM

Default `MODEL_MODE=openrouter`, model `openai/gpt-5.5` via `https://openrouter.ai/api/v1`:
- `response_format=json_schema` (strict) for schema-enforced extraction, plus
  `provider:{require_parameters:true}` so OpenRouter only routes to a provider that
  honors structured outputs (otherwise it can be silently dropped).
- gpt-5.5 is a **reasoning model** → `temperature` is not sent; uses `max_tokens`
  (the slug's OpenRouter endpoint advertises `max_tokens`).
- For a deterministic non-reasoning model, set `OPENROUTER_MODEL=openai/gpt-4.1`,
  `REASONING_MODEL=false`, `LLM_TEMPERATURE=0`.

Other backends remain available: `MODEL_MODE=azure` (Azure OpenAI `gpt-5.5`,
`api-version` ≥ `2025-04-01-preview`, `max_completion_tokens`, no temperature) and
`MODEL_MODE=openai_compatible` (a LiteLLM-style proxy via `OPENAI_COMPAT_BASE_URL`).

## API

- `POST /hooks/meeting-completed` — accepts the Vexa envelope, ACKs **202 immediately**,
  processes in the background, idempotent on `event_id`.
- `GET /health`.

## Kanban adapter

`app/kanban_client.py` is the single, clearly-marked adapter boundary. With no
`KANBAN_API_URL` set it logs the payload it would send; otherwise it makes a generic
best-effort POST. **Wire your real endpoints/auth/payload there.**

## Config & run

All config via env — see [`.env.example`](.env.example). Built and wired through the
repo-root [`docker-compose.azure.yml`](../../docker-compose.azure.yml). Trigger by setting
in `.env`:

```
POST_MEETING_HOOKS=http://standup-extractor:8086/hooks/meeting-completed
```

Unit tests (no Azure needed): `pytest tests/ -v`.

## Vexa core files touched

**None.** Integration is via env (`POST_MEETING_HOOKS`) + the compose overlay. See
[`../../CHANGES.md`](../../CHANGES.md).
