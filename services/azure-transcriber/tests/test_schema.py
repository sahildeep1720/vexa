"""Unit tests for the Azure -> Vexa response translators (no network / Azure needed)."""
from app import schema


def test_openai_verbose_passthrough_with_words():
    azure = {
        "text": "Hello world",
        "language": "english",            # full name -> must normalize to 'en'
        "duration": 3.2,
        "segments": [
            {
                "id": 0, "start": 0.0, "end": 3.2, "text": "Hello world",
                "avg_logprob": -0.2, "no_speech_prob": 0.01, "compression_ratio": 1.1,
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.5, "probability": 0.9},
                    {"word": "world", "start": 0.6, "end": 1.2, "probability": 0.8},
                ],
            }
        ],
    }
    out = schema.from_openai_verbose(azure, fallback_language=None, default_language_probability=1.0)
    assert out["text"] == "Hello world"
    assert out["language"] == "en"
    assert out["language_probability"] == 1.0          # azure omitted it -> default
    assert out["duration"] == 3.2
    assert len(out["segments"]) == 1
    seg = out["segments"][0]
    assert seg["avg_logprob"] == -0.2
    assert len(seg["words"]) == 2
    assert seg["words"][0]["word"] == "Hello"


def test_openai_verbose_derives_text_and_duration_when_missing():
    azure = {"language": "en", "segments": [
        {"start": 0.0, "end": 1.0, "text": " a"},
        {"start": 1.0, "end": 2.5, "text": " b"},
    ]}
    out = schema.from_openai_verbose(azure, fallback_language="en", default_language_probability=1.0)
    assert out["text"] == "a b"
    assert out["duration"] == 2.5


def test_diarized_drops_speaker_keeps_text():
    azure = {
        "text": "hi there",
        "segments": [
            {"speaker": "A", "start": 0.0, "end": 1.0, "text": "hi"},
            {"speaker": "B", "start": 1.0, "end": 2.0, "text": "there"},
        ],
    }
    out = schema.from_diarized(azure, fallback_language="en", default_language_probability=1.0)
    assert out["text"] == "hi there"
    assert out["language"] == "en"
    assert all("speaker" not in s for s in out["segments"])   # Vexa ignores transcriber speaker
    assert all("words" not in s for s in out["segments"])     # no word timestamps from diarize
    assert out["segments"][1]["start"] == 1.0


def test_azure_speech_ms_to_seconds():
    azure = {
        "durationMilliseconds": 2000,
        "combinedPhrases": [{"text": "good morning"}],
        "phrases": [
            {
                "offsetMilliseconds": 500, "durationMilliseconds": 1500,
                "text": "good morning", "locale": "en-US",
                "words": [
                    {"text": "good", "offsetMilliseconds": 500, "durationMilliseconds": 400},
                    {"text": "morning", "offsetMilliseconds": 900, "durationMilliseconds": 1100},
                ],
            }
        ],
    }
    out = schema.from_azure_speech(azure, fallback_language=None, default_language_probability=1.0)
    assert out["text"] == "good morning"
    assert out["language"] == "en"                # en-US -> en
    assert out["duration"] == 2.0
    seg = out["segments"][0]
    assert seg["start"] == 0.5
    assert seg["end"] == 2.0
    assert seg["words"][0]["word"] == "good"
    assert seg["words"][0]["start"] == 0.5
    assert seg["words"][1]["end"] == 2.0          # (900 + 1100)/1000


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
