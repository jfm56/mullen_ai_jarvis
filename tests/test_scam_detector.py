"""Scam/phishing detector.

These cover the obvious-positive and obvious-negative cases. Borderline
cases will need real-inbox tuning later, but the floor must be solid.
"""

from __future__ import annotations

import pytest

from app.agents.email_assistant.scam import detect


def test_clean_email_scores_zero() -> None:
    r = detect(
        from_addr="alice@mullenanalytics.com",
        subject="lunch tomorrow?",
        body_text="hey jim, want to grab lunch tomorrow at noon?",
    )
    assert r.score == 0.0
    assert r.signals == []
    assert r.is_likely_scam is False


def test_classic_wire_fraud_is_flagged() -> None:
    r = detect(
        from_addr="urgent@accounting-payroll.com",
        subject="URGENT - wire transfer needed today",
        body_text=(
            "Jim, I need you to process a wire transfer of $24,500 to a new "
            "vendor immediately. Account suspended if not processed today. "
            "Please act now."
        ),
    )
    assert r.is_likely_scam is True
    assert "urgency_pressure" in r.signals
    assert "financial_action_requested" in r.signals
    assert "account_threat" in r.signals


def test_credential_phish_is_flagged() -> None:
    r = detect(
        from_addr="security@paypa1.com",
        subject="Verify your account immediately",
        body_text=(
            "Unusual sign-in detected. Click here to verify your password "
            "and confirm your bank account details right away."
        ),
    )
    assert r.is_likely_scam is True
    assert "credential_request" in r.signals
    assert any(s.startswith("sender_domain_lookalike:") for s in r.signals)


def test_lookalike_domain_digit_substitution() -> None:
    # paypa1 → paypal via 1→l
    r = detect(from_addr="x@paypa1.com", subject="t", body_text="")
    assert any("paypal" in s for s in r.signals)


def test_link_text_mismatch_flagged() -> None:
    r = detect(
        from_addr="news@example.com",
        subject="quarterly update",
        body_text="See the report.",
        body_html='<p>See <a href="https://evil-tracker.ru/abc">paypal.com/account</a></p>',
    )
    assert "link_text_mismatch" in r.signals


def test_newsletter_unsubscribe_is_not_flagged() -> None:
    # Newsletters often have click-bait-ish words; should not trip the scam detector.
    r = detect(
        from_addr="news@substack.com",
        subject="This week in AI",
        body_text="Hey there! Click here to read this week's roundup. Unsubscribe at the bottom.",
    )
    # Click-bait alone shouldn't push us over 0.6.
    assert r.is_likely_scam is False


def test_score_is_clipped_to_one() -> None:
    r = detect(
        from_addr="threat@security-paypa1.com",
        subject="URGENT account suspended verify password wire transfer immediately",
        body_text="bitcoin gift card account locked verify pin password right away",
    )
    assert r.score <= 1.0
    assert r.is_likely_scam is True
