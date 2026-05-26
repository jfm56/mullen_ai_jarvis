"""Encrypted backup + restore.

Design:
  * pg_dump streams its output through AES-256-GCM into a `.dump.enc` file.
  * The 256-bit key lives in OS keyring under name `backup_master_key`
    (set via `python -m app.cli init` or `keyring set`).
  * The on-disk format is:
        magic (8 bytes "JARVIS01")
        nonce (12 bytes)
        ciphertext... (streamed in 1 MiB chunks)
        tag   (16 bytes) — appended by GCM
    Per-chunk nonces aren't used — a single GCM seal covers the whole dump,
    so a partial download is unusable. Acceptable since backups are local.
  * Restore reverses the format, streams plaintext to `pg_restore`.

This module deliberately does NOT shell out via the agent's
`subprocess_safe` (which is for agent-driven launches). It uses
`asyncio.create_subprocess_exec` directly with hard-coded executable
names looked up via `shutil.which`.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings
from app.integrations.computer import safe_path
from app.security import secrets

MAGIC = b"JARVIS01"
NONCE_LEN = 12
TAG_LEN = 16
_CHUNK = 1024 * 1024  # 1 MiB
_KEY_NAME = "backup_master_key"


class BackupError(RuntimeError):
    pass


@dataclass
class BackupResult:
    path: Path
    bytes_written: int
    sha256: str


def _key_bytes() -> bytes:
    try:
        b64 = secrets.get_secret(_KEY_NAME)
    except secrets.SecretNotFoundError as exc:
        raise BackupError(
            f"backup key not set; run `python -m app.cli init` "
            f"or `keyring set mullen_ai_jarvis {_KEY_NAME}`"
        ) from exc
    import base64

    try:
        key = base64.b64decode(b64)
    except Exception as exc:  # noqa: BLE001
        raise BackupError(f"backup key is not valid base64: {exc}") from exc
    if len(key) != 32:
        raise BackupError(f"backup key must be 32 bytes (got {len(key)})")
    return key


def generate_key_b64() -> str:
    """Return a fresh base64-encoded 32-byte key — store in keyring."""
    import base64

    return base64.b64encode(os.urandom(32)).decode("ascii")


def _which(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise BackupError(
            f"{name!r} not on PATH; install PostgreSQL client tools and re-try"
        )
    return found


def _parse_pg_url(url: str) -> dict[str, str]:
    """Pull host/port/db/user/password from a SQLAlchemy postgres URL.

    Format: postgresql[+driver]://user:password@host:port/dbname
    """
    from urllib.parse import urlparse

    parsed = urlparse(url.replace("+psycopg_async", "").replace("+psycopg", ""))
    if parsed.scheme not in ("postgresql", "postgres"):
        raise BackupError(f"unsupported URL scheme for backup: {parsed.scheme}")
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "",
        "password": parsed.password or "",
        "dbname": (parsed.path or "/").lstrip("/") or "",
    }


async def create_backup(*, output_dir: str | Path) -> BackupResult:
    """Run pg_dump and encrypt the stream. Returns the result + sha256.

    `output_dir` must be inside an allow-listed root (verified via safe_path).
    """
    out_root = safe_path.resolve_safe(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_root / f"jarvis-{ts}.dump.enc"

    key = _key_bytes()
    aesgcm = AESGCM(key)
    nonce = os.urandom(NONCE_LEN)

    settings = get_settings()
    pg = _parse_pg_url(settings.database_url)
    pg_dump = _which("pg_dump")

    env = os.environ.copy()
    if pg["password"]:
        env["PGPASSWORD"] = pg["password"]

    proc = await asyncio.create_subprocess_exec(
        pg_dump,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--host", pg["host"],
        "--port", pg["port"],
        "--username", pg["user"],
        pg["dbname"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    plaintext_chunks: list[bytes] = []
    assert proc.stdout is not None
    while True:
        chunk = await proc.stdout.read(_CHUNK)
        if not chunk:
            break
        plaintext_chunks.append(chunk)

    stderr_bytes = await proc.stderr.read() if proc.stderr else b""
    rc = await proc.wait()
    if rc != 0:
        raise BackupError(
            f"pg_dump failed (exit {rc}): {stderr_bytes.decode('utf-8', errors='replace')[:1000]}"
        )

    plaintext = b"".join(plaintext_chunks)
    ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=MAGIC)

    sha = hashlib.sha256()
    with out_path.open("wb") as f:
        f.write(MAGIC)
        sha.update(MAGIC)
        f.write(nonce)
        sha.update(nonce)
        f.write(ciphertext)
        sha.update(ciphertext)
    return BackupResult(
        path=out_path,
        bytes_written=out_path.stat().st_size,
        sha256=sha.hexdigest(),
    )


async def restore_backup(*, backup_path: str | Path) -> None:
    """Decrypt the dump and stream it into pg_restore. DESTRUCTIVE on the target DB."""
    src = safe_path.resolve_safe(backup_path, must_exist=True)
    key = _key_bytes()
    aesgcm = AESGCM(key)

    raw = src.read_bytes()
    if len(raw) < len(MAGIC) + NONCE_LEN + TAG_LEN:
        raise BackupError("backup file is too short to be valid")
    if raw[: len(MAGIC)] != MAGIC:
        raise BackupError("backup file is missing expected magic header")
    nonce = raw[len(MAGIC) : len(MAGIC) + NONCE_LEN]
    ciphertext = raw[len(MAGIC) + NONCE_LEN :]

    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=MAGIC)
    except Exception as exc:  # InvalidTag / etc.
        raise BackupError(f"decryption failed (key wrong or file corrupted): {exc}") from exc

    settings = get_settings()
    pg = _parse_pg_url(settings.database_url)
    pg_restore = _which("pg_restore")

    env = os.environ.copy()
    if pg["password"]:
        env["PGPASSWORD"] = pg["password"]

    proc = await asyncio.create_subprocess_exec(
        pg_restore,
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--host", pg["host"],
        "--port", pg["port"],
        "--username", pg["user"],
        "--dbname", pg["dbname"],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout_b, stderr_b = await proc.communicate(input=plaintext)
    rc = await proc.wait()
    if rc != 0:
        raise BackupError(
            f"pg_restore failed (exit {rc}): "
            f"{stderr_b.decode('utf-8', errors='replace')[:1000]}"
        )
