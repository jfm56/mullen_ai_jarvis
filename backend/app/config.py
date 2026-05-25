"""Runtime configuration. Reads from environment with .env fallback.

Secrets (API keys, OAuth tokens) should NOT be loaded here in production —
use `app.security.secrets.get_secret(...)` which reads from the OS keyring.
This module is for non-secret operational settings only.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    development = "development"
    production = "production"
    test = "test"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_prefix="JARVIS_",
        extra="ignore",
    )

    env: Environment = Environment.development
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000

    secret_key: str = Field(default="dev-only-replace-me", min_length=16)
    access_token_ttl_min: int = 60

    default_permission: str = "ask_before_action"

    database_url: str = Field(
        default="postgresql+psycopg://jarvis:jarvis@localhost:5432/jarvis",
        alias="DATABASE_URL",
    )

    ollama_host: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_HOST")
    ollama_default_model: str = Field(default="llama3.1:8b", alias="OLLAMA_DEFAULT_MODEL")
    ollama_embedding_model: str = Field(
        default="nomic-embed-text", alias="OLLAMA_EMBEDDING_MODEL"
    )
    embedding_dim: int = Field(default=768, alias="EMBEDDING_DIM")

    whisper_model: str = Field(default="base.en", alias="WHISPER_MODEL")
    tts_voice: str = Field(default="default", alias="TTS_VOICE")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
