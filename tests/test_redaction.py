"""Sensitive-data redaction.

These tests are also the spec for what the scrubber catches. If a pattern
needs to change, the corresponding test should change too.
"""

from __future__ import annotations

import logging

import pytest

from app.security.redaction import RedactingFilter, install, redact


def test_redact_empty_string_returns_empty() -> None:
    assert redact("") == ""


def test_openai_key_redacted() -> None:
    s = "OPENAI_API_KEY=sk-proj-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
    out = redact(s)
    assert "<openai-key>" in out
    assert "aBcDeFg" not in out


def test_anthropic_key_redacted() -> None:
    s = "anthropic key sk-ant-api03-AbCdEf1234567890_XYZabc-Def123 here"
    assert "<anthropic-key>" in redact(s)


def test_jwt_redacted() -> None:
    fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3In0.abcdef"
    assert "<jwt>" in redact(fake_jwt)


def test_bearer_token_redacted_keeps_header_label() -> None:
    s = "Authorization: Bearer abc.def.ghi-jklmnop-12345678"
    out = redact(s)
    assert "<bearer-token>" in out
    assert "Authorization:" in out


def test_ssn_redacted() -> None:
    assert redact("SSN 123-45-6789 on file") == "SSN <ssn> on file"


def test_ssn_with_invalid_prefix_not_redacted() -> None:
    # 000-xx-xxxx and 666-xx-xxxx and 9xx-xx-xxxx are SSA-invalid by rule.
    assert "<ssn>" not in redact("000-12-3456")


def test_credit_card_redacted() -> None:
    s = "card 4111 1111 1111 1111 stored"
    out = redact(s)
    assert "<cc-num>" in out


def test_email_replaced_with_domain_only() -> None:
    s = "contact alice@example.com for details"
    out = redact(s)
    assert "alice" not in out
    assert "<email example.com>" in out
    # Replacement marker must not itself contain an '@' or repeated passes
    # would re-trigger the email rule.
    assert "@" not in out


def test_phone_redacted() -> None:
    for phone in ("555-867-5309", "(555) 867-5309", "+1 555-867-5309", "5558675309"):
        assert "<phone>" in redact(f"call {phone} please"), phone


def test_password_param_redacted() -> None:
    assert "password=<redacted>" in redact("password=hunter2 in url")
    assert "api_key=<redacted>" in redact("api_key:abc123 here")
    assert "token=<redacted>" in redact("...token: 'xyzpdq'...")


def test_github_token_redacted() -> None:
    s = "ghp_AbCdEf12345678901234567890ABCDef"
    assert "<github-token>" in redact(s)


def test_aws_access_key_redacted() -> None:
    assert "<aws-access-key>" in redact("AKIAIOSFODNN7EXAMPLE plus more")


def test_idempotent() -> None:
    s = "alice@example.com SSN 123-45-6789"
    once = redact(s)
    twice = redact(once)
    assert once == twice  # second pass changes nothing


def test_factory_scrubs_records_from_child_loggers(caplog: pytest.LogCaptureFixture) -> None:
    """The scrubber must catch records from ANY logger, not just root."""
    from app.security.redaction import uninstall

    install()
    try:
        with caplog.at_level(logging.INFO):
            logging.getLogger("jarvis.test.redaction.child").info(
                "user alice@example.com signed in with token=abcd1234"
            )
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "alice" not in joined
        assert "<email example.com>" in joined
        assert "token=<redacted>" in joined
    finally:
        uninstall()


def test_install_is_idempotent(caplog: pytest.LogCaptureFixture) -> None:
    """Calling install() many times must not chain factories or double-scrub."""
    from app.security.redaction import uninstall

    install()
    install()
    install()
    try:
        with caplog.at_level(logging.INFO):
            logging.getLogger("jarvis.test.redaction.idem").info(
                "email bob@example.org"
            )
        joined = " ".join(r.getMessage() for r in caplog.records)
        # Scrubbed exactly once: the marker should appear, the raw email should not.
        assert "<email example.org>" in joined
        assert "bob@example.org" not in joined
        # And the marker text has no '@', so it can't be re-scrubbed.
        assert "@" not in joined
    finally:
        uninstall()
