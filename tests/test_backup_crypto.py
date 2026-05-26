"""Backup encryption: round-trip a fake pg_dump payload.

The actual pg_dump call is patched — these tests verify the format,
key handling, and decryption-failure detection.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from app.integrations import backup
from app.integrations.computer import safe_path


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("JARVIS_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.setattr(safe_path, "_default_roots", lambda: [])
    return tmp_path


@pytest.fixture
def fixed_key(monkeypatch) -> bytes:
    key = b"\x00\x11\x22\x33\x44\x55\x66\x77" * 4  # 32 bytes
    monkeypatch.setattr(backup, "_key_bytes", lambda: key)
    return key


def test_generate_key_b64_is_32_bytes() -> None:
    b = base64.b64decode(backup.generate_key_b64())
    assert len(b) == 32


def test_missing_key_raises_backup_error(monkeypatch) -> None:
    from app.security import secrets as secret_store

    def fake_get(_name, **_kw):
        raise secret_store.SecretNotFoundError("nope")

    monkeypatch.setattr(secret_store, "get_secret", fake_get)
    with pytest.raises(backup.BackupError, match="not set"):
        backup._key_bytes()


def test_wrong_length_key_raises_backup_error(monkeypatch) -> None:
    short = base64.b64encode(b"too short").decode()
    monkeypatch.setattr(
        "app.integrations.backup.secrets.get_secret", lambda *_a, **_kw: short
    )
    with pytest.raises(backup.BackupError, match="32 bytes"):
        backup._key_bytes()


def test_invalid_base64_key_raises_backup_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.backup.secrets.get_secret", lambda *_a, **_kw: "!!!not base64!!!"
    )
    with pytest.raises(backup.BackupError, match="base64"):
        backup._key_bytes()


@pytest.mark.asyncio
async def test_full_create_and_restore_round_trip(
    sandbox: Path, fixed_key, monkeypatch
) -> None:
    payload = b"FAKE PG DUMP PAYLOAD " * 100

    # Mock pg_dump.
    class _FakeStdout:
        def __init__(self, data: bytes) -> None:
            self._data = data
            self._sent = False
        async def read(self, _n: int) -> bytes:
            if self._sent:
                return b""
            self._sent = True
            return self._data

    class _FakeStderr:
        async def read(self) -> bytes:
            return b""

    class _FakeProc:
        def __init__(self, stdout_data: bytes) -> None:
            self.stdout = _FakeStdout(stdout_data)
            self.stderr = _FakeStderr()
            self.returncode = 0
        async def wait(self) -> int:
            return 0
        async def communicate(self, input: bytes | None = None):
            self._restored = input
            return (b"", b"")

    restored_input: dict[str, bytes] = {}

    async def fake_exec(*args, **kwargs):
        if args[0].endswith("pg_dump") or args[0].endswith("pg_dump.exe"):
            return _FakeProc(payload)
        # pg_restore
        proc = _FakeProc(b"")
        proc._holder = restored_input  # type: ignore[attr-defined]
        async def communicate(input: bytes | None = None):
            restored_input["payload"] = input or b""
            return (b"", b"")
        proc.communicate = communicate  # type: ignore[assignment]
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    # Pretend pg_dump and pg_restore are installed.
    monkeypatch.setattr(
        backup, "_which", lambda name: f"/fake/{name}"
    )

    # Create.
    result = await backup.create_backup(output_dir=str(sandbox))
    assert result.path.exists()
    assert result.bytes_written > 0

    # File starts with magic + nonce.
    data = result.path.read_bytes()
    assert data[: len(backup.MAGIC)] == backup.MAGIC
    assert len(data) > len(backup.MAGIC) + backup.NONCE_LEN

    # Tampering invalidates the file.
    tampered = sandbox / "tampered.dump.enc"
    tampered.write_bytes(data[:-1] + bytes([data[-1] ^ 0x01]))
    with pytest.raises(backup.BackupError, match="decryption failed"):
        await backup.restore_backup(backup_path=str(tampered))

    # Restore — verify the payload that ended up on pg_restore's stdin matches.
    await backup.restore_backup(backup_path=str(result.path))
    assert restored_input["payload"] == payload


@pytest.mark.asyncio
async def test_restore_rejects_missing_magic(sandbox: Path, fixed_key) -> None:
    bad = sandbox / "bad.dump.enc"
    bad.write_bytes(b"NOTJARVIS" + os.urandom(64))
    with pytest.raises(backup.BackupError, match="magic"):
        await backup.restore_backup(backup_path=str(bad))


@pytest.mark.asyncio
async def test_restore_rejects_too_short(sandbox: Path, fixed_key) -> None:
    bad = sandbox / "tiny.dump.enc"
    bad.write_bytes(b"short")
    with pytest.raises(backup.BackupError, match="too short"):
        await backup.restore_backup(backup_path=str(bad))


def test_parse_pg_url_extracts_components() -> None:
    parts = backup._parse_pg_url(
        "postgresql+psycopg_async://alice:s3cret@db.example.com:5433/jarvis"
    )
    assert parts == {
        "host": "db.example.com",
        "port": "5433",
        "user": "alice",
        "password": "s3cret",
        "dbname": "jarvis",
    }


def test_parse_pg_url_defaults() -> None:
    parts = backup._parse_pg_url("postgresql://jarvis@localhost/jarvis")
    assert parts["port"] == "5432"
    assert parts["password"] == ""


def test_parse_pg_url_rejects_other_schemes() -> None:
    with pytest.raises(backup.BackupError):
        backup._parse_pg_url("sqlite:///foo.db")
