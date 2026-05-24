"""Speech-to-text via faster-whisper (local, offline).

Implemented in Phase 2 alongside the Personal Assistant.
"""

from __future__ import annotations


async def transcribe(audio_bytes: bytes, *, language: str = "en") -> str:
    raise NotImplementedError("voice.stt.transcribe — implement in Phase 2")
