"""Unit tests for the OpenRouter standup extractor: prompt, request body, key guard.

Dependency-light on purpose (no pytest-asyncio): the one coroutine under test is
driven with ``asyncio.run`` and never touches the network — it raises before any
HTTP call when the API key is missing, so ``http=None`` is a safe dummy.
"""
import asyncio

from app.config import Settings
from app.extractor import _SYSTEM, build_messages, build_request_body, StandupExtractor


# ---- (a) system prompt + message construction ---------------------------------

def test_system_prompt_demands_english_output():
    # Translate-to-English directive must be present.
    assert "ENGLISH" in _SYSTEM


def test_system_prompt_never_translates_names():
    assert "NEVER translate or transliterate speaker names" in _SYSTEM


def test_system_prompt_preserves_technical_terms():
    assert "Keep technical terms, product names, library names, and ticket IDs verbatim" in _SYSTEM


def test_build_messages_places_system_prompt_first():
    messages = build_messages("Alice: did x", ["Alice"])
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == _SYSTEM
    assert messages[1]["role"] == "user"
    assert "did x" in messages[1]["content"]


# ---- (b) request body ----------------------------------------------------------

def _settings(**overrides) -> Settings:
    base = dict(openrouter_api_key="sk-test", openrouter_model="openai/gpt-5.5")
    base.update(overrides)
    return Settings(**base)


def test_request_body_uses_strict_json_schema():
    body = build_request_body(_settings(), [])
    rf = body["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True


def test_request_body_provider_present_when_require_parameters_true():
    body = build_request_body(_settings(openrouter_require_parameters=True), [])
    assert body["provider"] == {"require_parameters": True}


def test_request_body_provider_absent_when_require_parameters_false():
    body = build_request_body(_settings(openrouter_require_parameters=False), [])
    assert "provider" not in body


def test_request_body_omits_temperature_for_reasoning_model():
    body = build_request_body(_settings(reasoning_model=True, llm_temperature=0.0), [])
    assert "temperature" not in body


def test_request_body_includes_temperature_for_non_reasoning_model():
    body = build_request_body(_settings(reasoning_model=False, llm_temperature=0.0), [])
    assert body["temperature"] == 0.0


def test_request_body_uses_max_tokens_from_max_completion_tokens():
    body = build_request_body(_settings(max_completion_tokens=1234), [])
    assert body["max_tokens"] == 1234
    assert body["model"] == "openai/gpt-5.5"


# ---- (c) missing-key guard -----------------------------------------------------

def test_extract_raises_without_api_key():
    extractor = StandupExtractor(_settings(openrouter_api_key=None), http=None)
    raised = False
    try:
        asyncio.run(extractor.extract("Alice: did x", ["Alice"]))
    except RuntimeError as e:
        raised = True
        assert "OPENROUTER_API_KEY is not configured" in str(e)
    assert raised
