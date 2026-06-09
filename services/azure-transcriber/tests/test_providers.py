"""Unit tests for the capability table + provider factory (no network needed)."""
import pytest

from app.config import Settings
from app.providers import CAPABILITIES, build_provider, resolve_model
from app.providers.base import ProviderError


def test_capability_table_models():
    assert set(CAPABILITIES) == {
        "openrouter",
        "gpt-4o-transcribe", "gpt-4o-mini-transcribe", "gpt-4o-transcribe-diarize",
        "whisper-1", "MAI-Transcribe-1",
    }


def test_openrouter_is_default_and_has_no_word_timestamps():
    assert Settings().transcriber_model == "openrouter"
    cap = CAPABILITIES["openrouter"]
    assert cap.api_kind == "openrouter"
    assert cap.word_timestamps is False   # OpenRouter STT is text-only


def test_diarize_has_no_word_timestamps():
    assert CAPABILITIES["gpt-4o-transcribe-diarize"].diarizes is True
    assert CAPABILITIES["gpt-4o-transcribe-diarize"].word_timestamps is False


def test_azure_model_supports_word_timestamps():
    cap = CAPABILITIES["gpt-4o-transcribe"]
    assert cap.api_kind == "azure_openai_rest"
    assert cap.word_timestamps is True


def test_resolve_aliases():
    assert resolve_model("whisper") == "whisper-1"
    assert resolve_model("mai") == "MAI-Transcribe-1"
    with pytest.raises(ValueError):
        resolve_model("not-a-model")


def test_build_openrouter_requires_key():
    s = Settings(transcriber_model="openrouter", openrouter_api_key=None)
    with pytest.raises(ProviderError):
        build_provider(s, http_client=None)


def test_build_openrouter_ok_with_key():
    s = Settings(transcriber_model="openrouter", openrouter_api_key="sk-or-x")
    prov = build_provider(s, http_client=object())
    assert prov.capability.api_kind == "openrouter"
    assert prov.slug == "openai/gpt-4o-transcribe"


def test_build_azure_rest_requires_endpoint():
    s = Settings(transcriber_model="gpt-4o-transcribe", azure_openai_endpoint=None)
    with pytest.raises(ProviderError):
        build_provider(s, http_client=None)


def test_build_azure_rest_ok_with_endpoint():
    s = Settings(transcriber_model="gpt-4o-transcribe",
                 azure_openai_endpoint="https://x.openai.azure.com",
                 azure_openai_api_key="k")
    prov = build_provider(s, http_client=object())
    assert prov.model_id == "gpt-4o-transcribe"
    assert prov.deployment == "gpt-4o-transcribe"
