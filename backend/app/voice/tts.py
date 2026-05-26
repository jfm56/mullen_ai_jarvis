"""Text-to-speech via Piper (local, offline).

Same shape as stt.py: lazy import, raises VoiceNotInstalledError when
piper-tts isn't installed, and runs the (CPU-bound) synthesis in a
worker thread so the event loop stays responsive.

Voice models are .onnx files downloaded separately from
https://github.com/rhasspy/piper#voices (each voice is ~70MB) and pointed
to via the `PIPER_VOICE_PATH` env var or the default in settings.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import wave
from typing import Any

from app.config import get_settings

logger = logging.getLogger("jarvis.voice.tts")


class VoiceNotInstalledError(RuntimeError):
    """Raised when piper-tts isn't installed."""


class SynthesisError(RuntimeError):
    """Raised for any other synthesis failure."""


_voice_cache: dict[str, Any] = {}


def _voice_path() -> str:
    """Resolve the voice model path. Order:
       JARVIS_PIPER_VOICE_PATH env -> settings.tts_voice."""
    path = os.environ.get("JARVIS_PIPER_VOICE_PATH") or get_settings().tts_voice
    if not path or path == "default":
        raise SynthesisError(
            "No Piper voice path configured. Download a .onnx voice from "
            "https://github.com/rhasspy/piper#voices and set "
            "JARVIS_PIPER_VOICE_PATH to its absolute path."
        )
    if not os.path.exists(path):
        raise SynthesisError(f"Piper voice file not found: {path}")
    return path


def _load_voice(path: str) -> Any:
    if path in _voice_cache:
        return _voice_cache[path]
    try:
        from piper import PiperVoice  # type: ignore[import-not-found]
    except ImportError as exc:
        raise VoiceNotInstalledError(
            "piper-tts not installed. Install with: "
            "pip install -e .[voice]  (from backend/)"
        ) from exc
    logger.info("loading piper voice %r", path)
    voice = PiperVoice.load(path)
    _voice_cache[path] = voice
    return voice


async def speak(text: str) -> bytes:
    """Synthesize `text` and return a complete WAV blob (16-bit mono PCM).

    Raises VoiceNotInstalledError / SynthesisError on failures.
    """
    if not text.strip():
        raise SynthesisError("text is empty")

    voice_path = _voice_path()
    voice = _load_voice(voice_path)

    def _run() -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            # synthesize_wav writes the proper RIFF header + PCM samples.
            voice.synthesize_wav(text, wav)
        return buf.getvalue()

    return await asyncio.to_thread(_run)


def is_available() -> bool:
    """True if piper can be imported AND a voice path resolves to a real file."""
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    try:
        _voice_path()
        return True
    except SynthesisError:
        return False
