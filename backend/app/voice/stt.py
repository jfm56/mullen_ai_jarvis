"""Speech-to-text via faster-whisper (local, offline).

Designed so that the rest of the app — and the test suite — never
imports `faster_whisper` at module load. The model is imported and
loaded on first `transcribe()` call, and that call returns a
`VoiceNotInstalledError` (subclass of RuntimeError) if the optional
extra isn't installed.

Configure via settings: `whisper_model` (default `base.en`).
Models download on first use into the HuggingFace cache (~150MB for base.en).
"""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger("jarvis.voice.stt")


class VoiceNotInstalledError(RuntimeError):
    """Raised when the voice extra (faster-whisper) isn't installed."""


class TranscriptionError(RuntimeError):
    """Raised for any other transcription failure."""


@dataclass
class Transcript:
    text: str
    language: str | None
    duration_s: float


_model_cache: dict[str, Any] = {}


def _load_model(name: str) -> Any:
    """Load a WhisperModel instance, caching by name. Raises VoiceNotInstalledError
    if faster-whisper isn't available."""
    if name in _model_cache:
        return _model_cache[name]
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError as exc:
        raise VoiceNotInstalledError(
            "faster-whisper not installed. Install with: "
            "pip install -e .[voice]  (from backend/)"
        ) from exc

    # CPU by default. compute_type=int8 keeps RAM modest; user can override
    # later by setting JARVIS_WHISPER_COMPUTE_TYPE.
    import os
    compute = os.environ.get("JARVIS_WHISPER_COMPUTE_TYPE", "int8")
    device = os.environ.get("JARVIS_WHISPER_DEVICE", "cpu")
    logger.info("loading whisper model %r (device=%s, compute=%s)", name, device, compute)
    model = WhisperModel(name, device=device, compute_type=compute)
    _model_cache[name] = model
    return model


async def transcribe(
    audio_bytes: bytes,
    *,
    language: str | None = "en",
    model: str | None = None,
) -> Transcript:
    """Transcribe an audio blob. Returns text + detected language + duration.

    `audio_bytes` should be a complete container (WAV, MP3, WebM/Opus, etc.)
    — faster-whisper / ffmpeg sniff the format. We write to a temp file
    because the underlying lib prefers a path or numpy array; in-memory
    decode is fragile across browsers and container formats.
    """
    if not audio_bytes:
        raise TranscriptionError("audio_bytes is empty")

    chosen = model or get_settings().whisper_model
    whisper_model = _load_model(chosen)

    def _run() -> Transcript:
        # Use a NamedTemporaryFile so the lib can sniff the format. Suffix is
        # irrelevant — faster-whisper hands off to ffmpeg.
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(audio_bytes)
            path = Path(f.name)
        try:
            segments, info = whisper_model.transcribe(
                str(path),
                language=language,
                vad_filter=True,
                beam_size=1,
            )
            text = "".join(seg.text for seg in segments).strip()
            return Transcript(
                text=text,
                language=getattr(info, "language", None),
                duration_s=float(getattr(info, "duration", 0.0)),
            )
        finally:
            try:
                path.unlink()
            except OSError:
                pass

    # Run the (CPU-bound, blocking) transcription in a thread so we don't
    # stall the event loop.
    return await asyncio.to_thread(_run)


def is_available() -> bool:
    """True if faster-whisper can be imported (without instantiating a model)."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


_ = io  # kept for forward-compat; transcribe may switch to in-memory paths
