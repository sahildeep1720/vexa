"""transcriber — OpenAI-compatible transcription facade over OpenRouter.

A drop-in replacement for Vexa's transcription-service: identical inbound contract
(``POST /v1/audio/transcriptions``, multipart) and identical outbound verbose_json,
so Vexa talks to it exactly as it talks to the bundled WhisperLive service. The
backend OpenRouter model is chosen by ``OPENROUTER_TRANSCRIBE_MODEL`` (one-line env
swap). The inbound ``model`` form field (Vexa always sends ``whisper-1``) is ignored.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse

from .config import load_settings
from .providers import CAPABILITIES, build_provider
from .providers.base import ProviderError

settings = load_settings()
logging.basicConfig(
    level=getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("transcriber")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        timeout=settings.request_timeout_s,
    )
    app.state.provider = None
    app.state.provider_error = None
    try:
        app.state.provider = build_provider(settings, app.state.http)
        logger.info("transcriber ready: model=%s api_kind=%s",
                    app.state.provider.model_id, app.state.provider.capability.api_kind)
    except Exception as e:  # keep /health serving so the error is visible
        app.state.provider_error = str(e)
        logger.error("Provider init failed: %s", e)
    yield
    await app.state.http.aclose()


app = FastAPI(title="transcriber", lifespan=lifespan)


def _auth_error(authorization: Optional[str], x_api_key: Optional[str]) -> Optional[JSONResponse]:
    token = settings.inbound_auth_token
    if not token:
        return None
    presented = None
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:]
    elif x_api_key:
        presented = x_api_key
    if presented != token:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return None


@app.get("/health")
async def health():
    # Liveness: 200 whenever the process is up. `ready` reflects whether the
    # selected provider initialised (e.g. OpenRouter creds present). A misconfigured
    # backend reports ready=false rather than crash-looping the container.
    ready = app.state.provider is not None
    body = {
        "status": "ok",
        "ready": ready,
        "model": settings.transcriber_model,
    }
    if ready:
        body["api_kind"] = app.state.provider.capability.api_kind
    else:
        body["error"] = app.state.provider_error or "provider not initialised"
    return JSONResponse(body, status_code=200)


@app.get("/")
async def root():
    return {
        "service": "transcriber",
        "active_model": settings.transcriber_model,
        "endpoints": {"transcribe": "/v1/audio/transcriptions", "health": "/health"},
        "capabilities": {
            m: {"api_kind": c.api_kind, "word_timestamps": c.word_timestamps}
            for m, c in CAPABILITIES.items()
        },
    }


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),  # sent by Vexa; ignored in favour of TRANSCRIBER_MODEL
    response_format: str = Form("verbose_json"),
    timestamp_granularities: str = Form("segment"),
    language: Optional[str] = Form(None),
    prompt: Optional[str] = Form(None),
    # accepted for OpenAI-contract compatibility with Vexa's bot; the OpenRouter
    # backend ignores VAD tuning fields
    max_speech_duration_s: Optional[str] = Form(None),
    min_silence_duration_ms: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    err = _auth_error(authorization, x_api_key)
    if err:
        return err
    if app.state.provider is None:
        return JSONResponse(
            {"detail": app.state.provider_error or "provider not ready"},
            status_code=503, headers={"Retry-After": str(settings.busy_retry_after_s)},
        )

    audio = await file.read()
    lang = None if (language in (None, "", "auto")) else language
    try:
        result = await app.state.provider.transcribe(
            audio,
            filename=file.filename or "audio.wav",
            content_type=file.content_type or "audio/wav",
            language=lang,
            prompt=prompt,
        )
        return JSONResponse(result)
    except ProviderError as e:
        logger.warning("transcription failed: %s", e)
        headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
        return JSONResponse({"detail": str(e)}, status_code=e.status_code, headers=headers)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        logger.warning("transcription timed out")
        return JSONResponse(
            {"detail": "upstream timeout"},
            status_code=503, headers={"Retry-After": str(settings.busy_retry_after_s)},
        )
    except Exception as e:  # never kill the meeting
        logger.exception("unexpected transcription error")
        return JSONResponse({"detail": f"internal error: {e}"}, status_code=500)
