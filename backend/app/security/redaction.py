"""Sensitive-data redaction for logs.

The audit log already only stores hashes, but the regular logger
(uvicorn access log, dev print, agent debug output) might capture
emails, NOFO bodies, draft replies, OAuth tokens, or API keys.

This module provides:
  * `redact(text)` — pure-function scrubber for ad-hoc use
  * `install(root_logger=None)` — wraps `logging.setLogRecordFactory` so
    every LogRecord (regardless of which logger created it) has its
    `msg` scrubbed at construction. We use the factory rather than a
    logging.Filter because filters on a logger only fire for that
    logger's own filter chain — they do NOT run for child loggers'
    records, so a root-logger filter doesn't actually scrub child output.

Patterns are conservative — false positives are fine (a few asterisks
in a log line don't hurt), but false negatives are a leak.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

REDACTED = "<redacted>"


# Each tuple: (pattern, replacement_label).
# Order matters — most specific first so a partial match doesn't eat a
# more specific one.
_RULES: list[tuple[re.Pattern[str], str]] = [
    # Anthropic FIRST so the looser OpenAI rule below doesn't grab it.
    (re.compile(r"sk-ant-(?:api03|admin01)-[A-Za-z0-9_-]{20,}"), "<anthropic-key>"),
    # OpenAI: `sk-...` but NOT `sk-ant-...` (anthropic handled above).
    (re.compile(r"sk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{20,}"), "<openai-key>"),

    # AWS access key id (deterministic 20-char shape).
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<aws-access-key>"),

    # GitHub PAT (classic + fine-grained).
    (re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"), "<github-token>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "<github-pat>"),

    # Generic 'Authorization: Bearer XYZ' header.
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._\-+/=]{16,}"),
     r"\1<bearer-token>"),

    # JWT — three base64url segments separated by dots.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b"),
     "<jwt>"),

    # US SSN (loose: nnn-nn-nnnn).
    (re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"), "<ssn>"),

    # Credit-card-like 13-19 digit runs with optional spaces/dashes (Luhn not enforced).
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "<cc-num>"),

    # Generic email — replaced with a marker that does NOT itself contain '@',
    # so repeated passes are idempotent.
    (re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"),
     r"<email \2>"),

    # US phone numbers (loose: optional country code, area, exchange, line).
    (re.compile(r"\b(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"),
     "<phone>"),

    # 'password=...' / 'api_key=...' / 'token=...' in URL-like params or key=value.
    (re.compile(r"(?i)\b(password|passwd|api[_-]?key|token|secret)\s*[=:]\s*['\"]?([^\s'\"&]+)"),
     r"\1=<redacted>"),
]


def redact(text: str, *, rules: Iterable[tuple[re.Pattern[str], str]] | None = None) -> str:
    """Return `text` with sensitive substrings replaced."""
    if not text:
        return text
    for pattern, repl in rules or _RULES:
        text = pattern.sub(repl, text)
    return text


# --- Global install via LogRecord factory ----------------------------------


_INSTALLED = False
_ORIGINAL_FACTORY: Any = None


def _scrubbing_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _ORIGINAL_FACTORY(*args, **kwargs)
    # Render the message NOW (with args), then store the scrubbed string and
    # clear args so any handler that re-formats sees only the scrubbed text.
    try:
        rendered = record.getMessage()
    except Exception:  # noqa: BLE001
        return record
    scrubbed = redact(rendered)
    if scrubbed != rendered:
        record.msg = scrubbed
        record.args = None
    return record


def install(root_logger: logging.Logger | None = None) -> None:  # noqa: ARG001 - kept for API compatibility
    """Wrap the global LogRecord factory so every record is scrubbed at creation.

    Idempotent. `root_logger` arg is kept for backward-compat; the factory
    is process-global, not logger-scoped.
    """
    global _INSTALLED, _ORIGINAL_FACTORY
    if _INSTALLED:
        return
    _ORIGINAL_FACTORY = logging.getLogRecordFactory()
    logging.setLogRecordFactory(_scrubbing_factory)
    _INSTALLED = True


def uninstall() -> None:
    """Restore the original factory. Useful for tests that need to assert
    on un-scrubbed log content from other tests."""
    global _INSTALLED, _ORIGINAL_FACTORY
    if not _INSTALLED:
        return
    logging.setLogRecordFactory(_ORIGINAL_FACTORY)
    _ORIGINAL_FACTORY = None
    _INSTALLED = False


# Kept for backward-compat with any code that referenced the old filter class.
class RedactingFilter(logging.Filter):
    """Legacy filter shim. Prefer `install()` which uses the record factory."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        scrubbed = redact(rendered)
        if scrubbed != rendered:
            record.msg = scrubbed
            record.args = None
        return True
