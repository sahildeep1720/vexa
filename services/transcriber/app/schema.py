"""Translate the transcription backend's response into Vexa's verbose_json contract.

Vexa's bot (services/vexa-bot/core/src/services/transcription-client.ts) expects:

  {text, language, language_probability, duration,
   segments: [{start, end, text, avg_logprob?, no_speech_prob?, compression_ratio?,
               words?: [{word, start, end, probability}]}]}

The bot performs its OWN speaker attribution from ``words`` + platform speaker
boundaries, so we preserve word timestamps wherever the upstream model provides
them, and we never emit a ``speaker`` field (Vexa would ignore it).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Minimal full-name -> ISO-639-1 map for languages the backend may return as
# full names. 2-letter codes pass through; "en-US" -> "en"; unknowns fall back to
# the requested language or 'en'. Vexa validates segment.language against ISO
# faster-whisper codes downstream, so non-ISO values would be rejected.
_LANG_NAME_TO_CODE = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de",
    "italian": "it", "portuguese": "pt", "dutch": "nl", "russian": "ru",
    "chinese": "zh", "japanese": "ja", "korean": "ko", "arabic": "ar",
    "hindi": "hi", "turkish": "tr", "polish": "pl", "ukrainian": "uk",
    "swedish": "sv", "norwegian": "no", "danish": "da", "finnish": "fi",
    "czech": "cs", "greek": "el", "hebrew": "he", "thai": "th",
    "vietnamese": "vi", "indonesian": "id", "romanian": "ro", "hungarian": "hu",
}


def normalize_language(value: Optional[str], fallback: Optional[str]) -> str:
    if value:
        v = value.strip().lower()
        if "-" in v:                      # en-US -> en
            v = v.split("-", 1)[0]
        if len(v) == 2:
            return v
        if v in _LANG_NAME_TO_CODE:
            return _LANG_NAME_TO_CODE[v]
    if fallback:
        fb = fallback.strip().lower()
        return fb.split("-", 1)[0] if "-" in fb else fb
    return "en"


def _envelope(text, language, language_probability, duration, segments) -> Dict[str, Any]:
    return {
        "text": text or "",
        "language": language,
        "language_probability": float(language_probability),
        "duration": float(duration or 0.0),
        "segments": segments or [],
    }


def from_openrouter_text(text: Optional[str], *, duration: float, fallback_language: Optional[str],
                         default_language_probability: float) -> Dict[str, Any]:
    """OpenRouter /audio/transcriptions ({text} only) -> Vexa verbose_json.

    OpenRouter returns no timestamps, so we synthesize ONE segment spanning the
    whole chunk [0, duration] and emit no words. This keeps Vexa's sliding-window
    confirmation working at chunk granularity; word-level speaker splitting is not
    possible from this backend.
    """
    text = (text or "").strip()
    segments: List[Dict[str, Any]] = []
    if text:
        segments = [{"start": 0.0, "end": float(duration or 0.0), "text": text}]
    return _envelope(text, normalize_language(None, fallback_language),
                     default_language_probability, duration, segments)


def from_openai_verbose(data: Dict[str, Any], *, fallback_language: Optional[str],
                        default_language_probability: float) -> Dict[str, Any]:
    """OpenAI/Azure gpt-4o-transcribe / whisper verbose_json -> Vexa, with word timestamps.

    Returns per-segment + per-word timestamps for accurate per-speaker attribution.
    NOTE: whisper returns the word list at the TOP LEVEL (not inside each segment),
    so we distribute those words into their segments by time — the bot reads
    per-segment ``words``.
    """
    raw_segments = data.get("segments") or []
    top_words = data.get("words") or []
    wi = 0
    segments: List[Dict[str, Any]] = []
    for idx, s in enumerate(raw_segments):
        seg: Dict[str, Any] = {
            "start": float(s.get("start") or 0.0),
            "end": float(s.get("end") or 0.0),
            "text": s.get("text") or "",
        }
        for k in ("avg_logprob", "no_speech_prob", "compression_ratio"):
            if s.get(k) is not None:
                seg[k] = s[k]
        words = s.get("words")
        if not words and top_words:
            # whisper words are top-level; assign each to its segment by start time
            # (last segment absorbs the remainder so nothing is dropped).
            is_last = idx == len(raw_segments) - 1
            words = []
            while wi < len(top_words) and (is_last or float(top_words[wi].get("start") or 0.0) < seg["end"]):
                words.append(top_words[wi])
                wi += 1
        if words:
            seg["words"] = [
                {
                    "word": w.get("word", ""),
                    "start": float(w.get("start") or 0.0),
                    "end": float(w.get("end") or 0.0),
                    "probability": float(w.get("probability") if w.get("probability") is not None else 1.0),
                }
                for w in words
            ]
        segments.append(seg)

    duration = data.get("duration")
    if duration is None and segments:
        duration = segments[-1]["end"]
    text = data.get("text")
    if not text and segments:
        text = " ".join(seg["text"].strip() for seg in segments).strip()
    lang_prob = data.get("language_probability")
    if lang_prob is None:
        lang_prob = default_language_probability
    return _envelope(text, normalize_language(data.get("language"), fallback_language),
                     lang_prob, duration, segments)
