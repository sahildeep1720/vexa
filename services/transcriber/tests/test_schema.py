"""Unit tests for the backend -> Vexa response translators (no network needed)."""
from app import schema


def test_normalize_language():
    assert schema.normalize_language("english", None) == "en"
    assert schema.normalize_language("EN", None) == "en"
    assert schema.normalize_language("en-US", None) == "en"
    assert schema.normalize_language(None, "fr") == "fr"
    assert schema.normalize_language("klingon", None) == "en"   # unknown -> fallback 'en'


def test_openrouter_text_single_segment():
    out = schema.from_openrouter_text("hello there", duration=4.0, fallback_language="en",
                                      default_language_probability=1.0)
    assert out["text"] == "hello there"
    assert out["language"] == "en"
    assert out["duration"] == 4.0
    assert len(out["segments"]) == 1
    seg = out["segments"][0]
    assert seg["start"] == 0.0 and seg["end"] == 4.0
    assert "words" not in seg          # OpenRouter gives no word timestamps


def test_openrouter_empty_text_no_segment():
    out = schema.from_openrouter_text("", duration=2.0, fallback_language=None,
                                      default_language_probability=1.0)
    assert out["text"] == ""
    assert out["segments"] == []
