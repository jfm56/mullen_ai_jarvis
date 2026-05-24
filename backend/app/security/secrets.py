"""Secrets accessor.

Production: Windows Credential Manager via `keyring`.
Development: falls back to environment variable (from .env) if keyring miss
and JARVIS_ENV=development.

API keys, OAuth refresh tokens, and similar must use this module rather
than reading os.environ directly so that production deployments do not
end up with secrets on disk.
"""

from __future__ import annotations

import os

import keyring

from app.config import Environment, get_settings

_SERVICE_NAME = "mullen_ai_jarvis"


class SecretNotFoundError(LookupError):
    pass


def get_secret(name: str, *, env_var: str | None = None) -> str:
    """Return a secret by logical name.

    Lookup order:
      1. Keyring entry under service 'mullen_ai_jarvis', key = name.
      2. In development only, the env var (defaults to name.upper()).
    """
    value = keyring.get_password(_SERVICE_NAME, name)
    if value:
        return value

    if get_settings().env is Environment.development:
        fallback = os.environ.get(env_var or name.upper())
        if fallback:
            return fallback

    raise SecretNotFoundError(f"secret '{name}' not found in keyring")


def set_secret(name: str, value: str) -> None:
    keyring.set_password(_SERVICE_NAME, name, value)


def delete_secret(name: str) -> None:
    try:
        keyring.delete_password(_SERVICE_NAME, name)
    except keyring.errors.PasswordDeleteError:
        pass
