# azure-transcriber

An **OpenAI-compatible transcription facade** for Vexa. It is a drop-in replacement
for Vexa's bundled `transcription-service`: same inbound contract (`POST
/v1/audio/transcriptions`, multipart) and same outbound `verbose_json`, so Vexa talks
to it exactly as it talks to WhisperLive. The backend is pluggable via
`TRANSCRIBER_MODEL` — **default is OpenRouter**; Azure backends remain selectable.

> Name note: the directory is still `azure-transcriber` for continuity, but the
> default backend is now OpenRouter. It is a multi-backend transcription gateway.

## Inbound contract (unchanged, what Vexa sends)

`POST /v1/audio/transcriptions` multipart (`file`, `model`, `response_format`,
`timestamp_granularities`, `language`, …) → returns Vexa `verbose_json`
`{text, language, language_probability, duration, segments:[{start,end,text,words?}]}`.
The inbound `model` (Vexa sends `whisper-1`) is ignored; the active backend is
`TRANSCRIBER_MODEL`.

## Backends

| `TRANSCRIBER_MODEL` | api_kind | word ts | notes |
|---|---|---|---|
| `openrouter` *(default)* | openrouter | ✗ | OpenRouter `/audio/transcriptions` (JSON+base64); **text only** → we synthesize one full-chunk segment |
| `gpt-4o-transcribe` | azure_openai_rest | ✅ | Azure; verbose_json + word timestamps |
| `gpt-4o-mini-transcribe` | azure_openai_rest | ✅ | Azure; cheaper |
| `gpt-4o-transcribe-diarize` | azure_openai_rest | ✗ | Azure; `diarized_json`, segment-level |
| `whisper-1` | azure_openai_rest | ⚠️ | Azure; 25 MB cap |
| `MAI-Transcribe-1` | azure_speech_llm | ✅ | Azure Speech fast transcription |

Switching backend is one env line (`TRANSCRIBER_MODEL`) plus that backend's creds.

## OpenRouter backend — the timestamp tradeoff (read this)

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

If word-level speaker splitting matters, set `TRANSCRIBER_MODEL=gpt-4o-transcribe`
(Azure) or point at a local Whisper that returns `verbose_json`.

OpenRouter slugs are **namespaced** (e.g. `openai/gpt-4o-transcribe`, not `gpt-4o-transcribe`).

## Robustness

Retries OpenRouter/Azure 429/503 + network errors with bounded backoff; maps upstream
busy/timeouts to **HTTP 503 + `Retry-After`** (Vexa's bot already retries) — a failed
chunk never kills the meeting. `REQUEST_TIMEOUT_S` defaults to 25 s (< the bot's 30 s).
Azure verbose_json often omits `language_probability`, so we default it high
(`DEFAULT_LANGUAGE_PROBABILITY=1.0`) to avoid Vexa dropping auto-detected segments.

## Config & run

All config via env — see [`.env.example`](.env.example). Wired through the repo-root
[`docker-compose.azure.yml`](../../docker-compose.azure.yml); Vexa is repointed in `.env`:

```
TRANSCRIPTION_SERVICE_URL=http://azure-transcriber:8085/v1/audio/transcriptions
TRANSCRIPTION_SERVICE_TOKEN=<token this service accepts>
OPENROUTER_API_KEY=<your key>
```

Unit tests (no network needed): `pytest tests/ -v`.

## Vexa core files touched

**None.** Integration is env (`TRANSCRIPTION_SERVICE_URL`) + the compose overlay.
