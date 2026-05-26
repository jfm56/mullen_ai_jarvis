"""Voice endpoints + wrappers.

The real faster-whisper / piper models aren't installed in CI; we patch
the stt / tts modules to avoid the heavy deps.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.voice import stt, tts


# ---- stt + tts unit-level behavior ----------------------------------------


@pytest.mark.asyncio
async def test_stt_transcribe_rejects_empty_bytes() -> None:
    with pytest.raises(stt.TranscriptionError):
        await stt.transcribe(b"")


@pytest.mark.asyncio
async def test_stt_transcribe_raises_not_installed_when_lib_missing(monkeypatch) -> None:
    # Force the import to fail.
    monkeypatch.setitem(stt._model_cache, "fake", None)
    stt._model_cache.pop("fake", None)

    def fail_load(name: str) -> Any:
        raise stt.VoiceNotInstalledError("faster-whisper not installed.")

    monkeypatch.setattr(stt, "_load_model", fail_load)
    with pytest.raises(stt.VoiceNotInstalledError):
        await stt.transcribe(b"\x00\x01\x02", model="fake")


@pytest.mark.asyncio
async def test_stt_transcribe_happy_path(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeSegment:
        def __init__(self, text: str) -> None:
            self.text = text

    class FakeModel:
        def transcribe(self, path: str, **kwargs):  # noqa: ANN003
            captured["path"] = path
            captured["kwargs"] = kwargs
            return (
                iter([FakeSegment("Hello "), FakeSegment("world.")]),
                SimpleNamespace(language="en", duration=1.5),
            )

    monkeypatch.setattr(stt, "_load_model", lambda name: FakeModel())
    result = await stt.transcribe(b"FAKE AUDIO BYTES", language="en")
    assert result.text == "Hello world."
    assert result.language == "en"
    assert result.duration_s == 1.5
    assert captured["kwargs"]["language"] == "en"
    assert captured["kwargs"]["vad_filter"] is True


@pytest.mark.asyncio
async def test_tts_speak_rejects_empty_text() -> None:
    with pytest.raises(tts.SynthesisError):
        await tts.speak("")


@pytest.mark.asyncio
async def test_tts_speak_raises_not_installed_when_lib_missing(monkeypatch) -> None:
    monkeypatch.setattr(tts, "_voice_path", lambda: "/fake/voice.onnx")

    def fail_load(_p: str) -> Any:
        raise tts.VoiceNotInstalledError("piper-tts not installed.")

    monkeypatch.setattr(tts, "_load_voice", fail_load)
    with pytest.raises(tts.VoiceNotInstalledError):
        await tts.speak("hi")


@pytest.mark.asyncio
async def test_tts_speak_raises_synthesis_error_when_voice_missing(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_PIPER_VOICE_PATH", raising=False)
    # Bypass the import check so we don't accidentally hit the real piper module.
    monkeypatch.setattr(tts, "_load_voice", lambda _p: object())

    # Settings default tts_voice is 'default' which is not a real path.
    with pytest.raises(tts.SynthesisError):
        await tts.speak("hi")


@pytest.mark.asyncio
async def test_tts_speak_happy_path(monkeypatch, tmp_path) -> None:
    fake_voice_file = tmp_path / "voice.onnx"
    fake_voice_file.write_bytes(b"fake")
    monkeypatch.setenv("JARVIS_PIPER_VOICE_PATH", str(fake_voice_file))

    class FakeVoice:
        def synthesize_wav(self, text: str, wav) -> None:  # noqa: ANN001
            assert text == "hello"
            # Make it a valid 1-frame mono 16k PCM file.
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00")

    monkeypatch.setattr(tts, "_load_voice", lambda _p: FakeVoice())
    wav_bytes = await tts.speak("hello")
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes[:12]


# ---- API endpoints (mocked stt/tts) ---------------------------------------


def test_voice_status_endpoint_reports_unavailable_by_default(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.api.routes import voice as voice_route
    from app.db.models import User
    from app.security.auth import get_current_user

    fake_user = User(username="t", display_name="t", password_hash="x")

    monkeypatch.setattr(voice_route.stt, "is_available", lambda: False)
    monkeypatch.setattr(voice_route.tts, "is_available", lambda: False)

    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        client = TestClient(app)
        r = client.get("/voice/status")
        assert r.status_code == 200
        body = r.json()
        assert body["stt_available"] is False
        assert body["tts_available"] is False
        assert "voice" in body["notes"].lower() or "install" in body["notes"].lower()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_voice_transcribe_returns_503_when_lib_missing(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.api.routes import voice as voice_route
    from app.db.models import User
    from app.security.auth import get_current_user
    from app.voice import stt as stt_mod

    fake_user = User(username="t", display_name="t", password_hash="x")

    async def fake_transcribe(audio_bytes, *, language=None, model=None):  # noqa: ANN001
        raise stt_mod.VoiceNotInstalledError("not installed")

    monkeypatch.setattr(voice_route.stt, "transcribe", fake_transcribe)

    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        client = TestClient(app)
        r = client.post(
            "/voice/transcribe",
            files={"audio": ("x.wav", b"\x00\x01\x02", "audio/wav")},
        )
        assert r.status_code == 503
        assert "not installed" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_voice_transcribe_happy_path(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.api.routes import voice as voice_route
    from app.db.models import User
    from app.security.auth import get_current_user

    fake_user = User(username="t", display_name="t", password_hash="x")

    async def fake_transcribe(audio_bytes, *, language=None, model=None):  # noqa: ANN001
        return SimpleNamespace(text="hello world", language="en", duration_s=1.2)

    monkeypatch.setattr(voice_route.stt, "transcribe", fake_transcribe)

    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        client = TestClient(app)
        r = client.post(
            "/voice/transcribe",
            files={"audio": ("x.wav", b"\x00\x01\x02", "audio/wav")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["text"] == "hello world"
        assert body["language"] == "en"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_voice_speak_returns_wav_bytes(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.api.routes import voice as voice_route
    from app.db.models import User
    from app.security.auth import get_current_user

    fake_user = User(username="t", display_name="t", password_hash="x")

    async def fake_speak(text: str) -> bytes:
        # Minimal valid WAV header.
        return b"RIFF\x24\x00\x00\x00WAVEfmt "

    monkeypatch.setattr(voice_route.tts, "speak", fake_speak)

    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        client = TestClient(app)
        r = client.post("/voice/speak", json={"text": "hello jim"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/wav"
        assert r.content.startswith(b"RIFF")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_voice_speak_rejects_empty_text(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.db.models import User
    from app.security.auth import get_current_user

    fake_user = User(username="t", display_name="t", password_hash="x")

    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        client = TestClient(app)
        r = client.post("/voice/speak", json={"text": ""})
        # Pydantic validates min_length=1 -> 422
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_user, None)
