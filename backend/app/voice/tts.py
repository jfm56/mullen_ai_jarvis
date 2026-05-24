"""Text-to-speech (local: Piper or Coqui).

Implemented in Phase 2 alongside the Personal Assistant.
"""

from __future__ import annotations


async def speak(text: str, *, voice: str = "default") -> bytes:
    raise NotImplementedError("voice.tts.speak — implement in Phase 2")
