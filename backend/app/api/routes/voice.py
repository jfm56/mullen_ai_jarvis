"""Voice API.

POST /voice/transcribe — multipart audio upload, returns the transcript.
POST /voice/speak       — text in, audio/wav out.
GET  /voice/status      — capability probe (no audio I/O).

The agent-invocation flow is intentionally NOT bundled into this layer.
The frontend can chain: record -> /voice/transcribe -> /agents/<name>/handle
-> /voice/speak. Keeping each step explicit makes failures easier to
diagnose and lets the user mix-and-match (e.g., voice-in / text-out).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.db.models import User
from app.security.auth import get_current_user
from app.voice import stt, tts

router = APIRouter(prefix="/voice", tags=["voice"])


_MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MiB
_MAX_TTS_CHARS = 4000


class TranscriptView(BaseModel):
    text: str
    language: str | None
    duration_s: float


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=_MAX_TTS_CHARS)


class VoiceStatusView(BaseModel):
    stt_available: bool
    tts_available: bool
    notes: str


@router.get("/status", response_model=VoiceStatusView)
async def voice_status(_: Annotated[User, Depends(get_current_user)]) -> VoiceStatusView:
    stt_ok = stt.is_available()
    tts_ok = tts.is_available()
    notes = []
    if not stt_ok:
        notes.append("STT: install faster-whisper (pip install -e .[voice])")
    if not tts_ok:
        notes.append(
            "TTS: install piper-tts (pip install -e .[voice]) AND "
            "set JARVIS_PIPER_VOICE_PATH to a .onnx voice file"
        )
    return VoiceStatusView(
        stt_available=stt_ok,
        tts_available=tts_ok,
        notes="; ".join(notes) if notes else "ready",
    )


@router.post("/transcribe", response_model=TranscriptView)
async def transcribe(
    _: Annotated[User, Depends(get_current_user)],
    audio: UploadFile = File(...),
    language: str | None = "en",
) -> TranscriptView:
    data = await audio.read()
    if len(data) > _MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"audio too large ({len(data)} bytes; max {_MAX_AUDIO_BYTES})",
        )
    try:
        result = await stt.transcribe(data, language=language)
    except stt.VoiceNotInstalledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except stt.TranscriptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TranscriptView(
        text=result.text,
        language=result.language,
        duration_s=result.duration_s,
    )


@router.post("/speak")
async def speak(
    body: SpeakRequest,
    _: Annotated[User, Depends(get_current_user)],
) -> Response:
    try:
        wav = await tts.speak(body.text)
    except tts.VoiceNotInstalledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except tts.SynthesisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Content-Disposition": "inline; filename=jarvis.wav"},
        status_code=status.HTTP_200_OK,
    )
