"""Unit tests for the capability table + provider factory (no network needed)."""
import pytest

from app.config import Settings
from app.providers import CAPABILITIES, build_provider, resolve_model
from app.providers.base import ProviderError


def test_capability_table():
    assert "openrouter" in CAPABILITIES
    assert {"gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"} <= set(CAPABILITIES)
    assert CAPABILITIES["openrouter"].word_timestamps is False   # text-only
    assert CAPABILITIES["gpt-4o-transcribe"].word_timestamps is True
    assert CAPABILITIES["gpt-4o-transcribe"].api_kind == "azure_openai_rest"


def test_openrouter_is_default():
    assert Settings().transcriber_model == "openrouter"


def test_resolve_model():
    assert resolve_model("openrouter") == "openrouter"
    assert resolve_model("gpt-4o-transcribe") == "gpt-4o-transcribe"
    assert resolve_model("whisper") == "whisper-1"   # alias
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


def test_build_azure_requires_endpoint():
    s = Settings(transcriber_model="gpt-4o-transcribe", azure_openai_endpoint=None)
    with pytest.raises(ProviderError):
        build_provider(s, http_client=None)


def test_build_azure_ok_with_config():
    s = Settings(transcriber_model="gpt-4o-transcribe",
                 azure_openai_endpoint="https://r.openai.azure.com",
                 azure_openai_api_key="k")
    prov = build_provider(s, http_client=object())
    assert prov.capability.api_kind == "azure_openai_rest"
    assert prov.deployment == "gpt-4o-transcribe"   # deployment defaults to the model id
