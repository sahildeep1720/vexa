"""Unit tests for the capability table + provider factory (no network needed)."""
import pytest

from app.config import Settings
from app.providers import CAPABILITIES, build_provider, resolve_model
from app.providers.base import ProviderError


def test_openrouter_is_the_only_model():
    assert set(CAPABILITIES) == {"openrouter"}


def test_openrouter_is_default_and_has_no_word_timestamps():
    assert Settings().transcriber_model == "openrouter"
    cap = CAPABILITIES["openrouter"]
    assert cap.api_kind == "openrouter"
    assert cap.word_timestamps is False   # OpenRouter STT is text-only


def test_resolve_model_rejects_unknown():
    assert resolve_model("openrouter") == "openrouter"
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
