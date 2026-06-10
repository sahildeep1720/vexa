# transcriber

An **OpenAI-compatible transcription facade** for Vexa, backed by **OpenRouter**. It
is a drop-in replacement for Vexa's bundled `transcription-service`: same inbound
contract (`POST /v1/audio/transcriptions`, multipart) and same outbound `verbose_json`,
so Vexa talks to it exactly as it talks to WhisperLive. The OpenRouter model is
selected by `OPENROUTER_TRANSCRIBE_MODEL` — a one-line env change.

## Inbound contract (what Vexa sends)

`POST /v1/audio/transcriptions`, multipart, fields: `file`, `model`,
`response_format`, `timestamp_granularities`, `language?`, `max_speech_duration_s?`,
`min_silence_duration_ms?`, `prompt?`; `Authorization: Bearer <token>`. We accept all
of them for OpenAI-contract compatibility (the VAD tuning fields are ignored by the
OpenRouter backend). The inbound `model` field (Vexa sends `whisper-1`) is ignored;
the active backend is `OPENROUTER_TRANSCRIBE_MODEL`.

Returns Vexa `verbose_json`:
`{text, language, language_probability, duration, segments:[{start, end, text, words?}]}`.

## OpenRouter model

Set via `OPENROUTER_TRANSCRIBE_MODEL` using a **namespaced slug** (provider/model, NOT
a bare id). Default `openai/gpt-4o-transcribe`. Alternates:

- `openai/gpt-4o-mini-transcribe`
- `openai/whisper-large-v3`
- `openai/whisper-large-v3-turbo`
- `qwen/qwen3-asr-flash-2026-02-10`

## Timestamp tradeoff (read this)

OpenRouter's transcription endpoint returns **`{text}` only — no segment/word
timestamps, no `verbose_json`**. Vexa's bot, however, attributes speakers from Whisper
**word timestamps** and uses segment start/end to advance its sliding window. To keep
the pipeline working we **synthesize a single segment `[0, chunk_duration]`** (duration
parsed from the WAV header) carrying the full chunk text, with no `words`.

Consequence: speaker attribution degrades to **chunk granularity**.
- **Google Meet** captures per-speaker audio, so each chunk is already one speaker →
  attribution stays correct.
- **Teams** uses single-channel mixed audio + caption-boundary word mapping → without
  word timestamps, multiple speakers within a chunk can't be split. Coarser.

Any backend that speaks Vexa's `verbose_json` (e.g. a local Whisper that returns word
timestamps) can replace this service by repointing `TRANSCRIPTION_SERVICE_URL` — no
Vexa-core changes needed.

## Robustness

Retries OpenRouter 429/503 + network errors with bounded backoff; maps upstream
busy/timeouts to **HTTP 503 + `Retry-After`** (Vexa's bot already retries) — a failed
chunk never kills the meeting. `REQUEST_TIMEOUT_S` defaults to 25 s (kept **< the bot's
30 s** client timeout). OpenRouter STT omits `language_probability`, so we default it
high (`DEFAULT_LANGUAGE_PROBABILITY=1.0`) to avoid Vexa dropping auto-detected segments.

## Config

All config via env — see [`.env.example`](.env.example).

| Env | Default | Notes |
|---|---|---|
| `TRANSCRIBER_MODEL` | `openrouter` | The only backend; selects the OpenRouter provider |
| `OPENROUTER_API_KEY` | *(required)* | OpenRouter API key |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API base |
| `OPENROUTER_TRANSCRIBE_MODEL` | `openai/gpt-4o-transcribe` | Namespaced slug |
| `OPENROUTER_REFERER` | *(unset)* | Optional app-attribution header |
| `OPENROUTER_TITLE` | *(unset)* | Optional app-attribution header |
| `INBOUND_AUTH_TOKEN` | *(falls back to `TRANSCRIPTION_SERVICE_TOKEN`)* | If set, require matching `Bearer`/`X-API-Key` |
| `REQUEST_TIMEOUT_S` | `25` | Keep < the bot's 30 s timeout |
| `MAX_RETRIES` | `2` | Bounded retry count |
| `RETRY_BASE_MS` | `500` | Backoff base (network errors) |
| `BUSY_RETRY_AFTER_S` | `1` | `Retry-After` on 503 |
| `DEFAULT_LANGUAGE_PROBABILITY` | `1.0` | Emitted when backend omits it |
| `LOG_LEVEL` | `INFO` | Logging level |

Wired through the repo-root [`docker-compose.openrouter.yml`](../../docker-compose.openrouter.yml);
Vexa is repointed in `.env`:

```
TRANSCRIPTION_SERVICE_URL=http://transcriber:8085/v1/audio/transcriptions
TRANSCRIPTION_SERVICE_TOKEN=<token this service accepts>
OPENROUTER_API_KEY=<your key>
```

## Tests

Unit tests (no network needed): `pytest tests/ -v`.

## Vexa core files touched

**None.** Integration is env (`TRANSCRIPTION_SERVICE_URL`) + the compose overlay.
