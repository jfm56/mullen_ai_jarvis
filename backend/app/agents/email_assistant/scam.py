"""Scam / phishing detector.

Rule-based first-pass screen — runs locally, no LLM, no network.
Returns a 0..1 score and a list of triggered signals. The Email Assistant
uses score >= 0.6 as the threshold to mark `is_scam=True`, but the raw
signals are surfaced to the user so a borderline case can be reviewed.

This is deliberately conservative: false positives (legit email flagged)
are recoverable; false negatives (scam not flagged) cost the user money.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Patterns are intentionally broad. Each match contributes to the score
# with a weight; the final score is clipped to [0, 1].
_URGENCY_PHRASES = re.compile(
    r"\b(urgent|immediately|right away|act now|final notice|last chance|"
    r"within \d+ (?:hour|day)s?|expires? (?:today|tomorrow))\b",
    re.IGNORECASE,
)

_FINANCIAL_ACTION = re.compile(
    r"\b(wire transfer|gift card|bitcoin|crypto|western union|moneygram|"
    r"itunes card|google play card|amazon gift|prepaid card)\b",
    re.IGNORECASE,
)

_ACCOUNT_THREAT = re.compile(
    r"\b(account (?:suspended|locked|disabled|terminated|compromised)|"
    r"verify (?:your )?(?:account|identity|payment)|unusual (?:activity|sign-?in)|"
    r"unauthorized (?:access|login)|password (?:expired|reset required))\b",
    re.IGNORECASE,
)

_CLICK_BAIT = re.compile(
    r"\b(click (?:here|below)|tap (?:here|below)|open (?:the )?attachment|"
    r"download (?:the )?(?:invoice|document|file))\b",
    re.IGNORECASE,
)

_CREDENTIAL_REQUEST = re.compile(
    r"\b(confirm (?:your )?(?:password|ssn|social security|bank (?:account|details))|"
    r"verify (?:your )?(?:password|pin|otp|one[- ]time))\b",
    re.IGNORECASE,
)

# URLs with mismatched display text vs href are surfaced as a signal.
_LINK_RE = re.compile(r'<a\s[^>]*href=["\'](https?://[^"\']+)["\'][^>]*>([^<]+)</a>', re.IGNORECASE)

# Domain-like strings in link text (with or without protocol).
_BARE_URL = re.compile(r"https?://([\w.-]+)(?:/[^\s]*)?", re.IGNORECASE)
_LINK_TEXT_DOMAIN = re.compile(
    r"\b([a-z0-9][-a-z0-9]*(?:\.[a-z0-9][-a-z0-9]*)+)\b", re.IGNORECASE
)

# Common lookalike-domain tricks: 0/o, l/1, rn/m, paypa1.com, micros0ft, etc.
_SUSPICIOUS_DOMAIN_CHARS = re.compile(r"[0-9]")  # digits in domain body

_KNOWN_BRANDS = (
    "paypal", "microsoft", "amazon", "apple", "google", "chase", "wellsfargo",
    "bankofamerica", "fedex", "ups", "usps", "irs", "docusign", "dropbox",
    "linkedin", "facebook", "instagram",
)


@dataclass
class ScamResult:
    score: float
    signals: list[str]
    is_likely_scam: bool


def _domain_of(addr: str) -> str:
    if "@" in addr:
        return addr.rsplit("@", 1)[1].strip().rstrip(">").lower()
    return ""


def _looks_like_brand_lookalike(domain: str) -> str | None:
    """Return the brand being impersonated, or None."""
    bare = domain.split(".")[0] if "." in domain else domain
    for brand in _KNOWN_BRANDS:
        if brand in bare and bare != brand:
            # `paypal-secure-login` impersonates `paypal`; `paypal.com` doesn't.
            return brand
        # Same with digit substitution: paypa1, g00gle, micros0ft
        if _SUSPICIOUS_DOMAIN_CHARS.search(bare):
            stripped = re.sub(r"[01]", lambda m: {"0": "o", "1": "l"}[m.group()], bare)
            if stripped == brand:
                return brand
    return None


def detect(
    *,
    from_addr: str = "",
    subject: str = "",
    body_text: str = "",
    body_html: str = "",
) -> ScamResult:
    """Return a scam likelihood score and the list of triggered signals."""
    signals: list[str] = []
    score = 0.0

    blob = f"{subject}\n{body_text}".strip()

    if _URGENCY_PHRASES.search(blob):
        signals.append("urgency_pressure")
        score += 0.20
    if _FINANCIAL_ACTION.search(blob):
        signals.append("financial_action_requested")
        score += 0.40
    if _ACCOUNT_THREAT.search(blob):
        signals.append("account_threat")
        score += 0.30
    if _CLICK_BAIT.search(blob):
        signals.append("click_bait")
        score += 0.10
    if _CREDENTIAL_REQUEST.search(blob):
        signals.append("credential_request")
        score += 0.50

    # Sender domain check.
    sender_domain = _domain_of(from_addr)
    if sender_domain:
        brand = _looks_like_brand_lookalike(sender_domain)
        if brand:
            signals.append(f"sender_domain_lookalike:{brand}")
            score += 0.35

    # Link mismatch (display text says one thing, href goes elsewhere).
    if body_html:
        for href, text in _LINK_RE.findall(body_html):
            href_domain = href.split("://", 1)[-1].split("/", 1)[0].lower()
            # Try protocol-prefixed first, then any bare domain-shaped string.
            text_domains = _BARE_URL.findall(text) or _LINK_TEXT_DOMAIN.findall(text)
            if text_domains:
                shown = text_domains[0].lower()
                if shown and shown != href_domain and not (
                    shown.endswith("." + href_domain) or href_domain.endswith("." + shown)
                ):
                    signals.append("link_text_mismatch")
                    score += 0.30
                    break

    # Mention of well-known brand in body but sender is on a different domain.
    if sender_domain:
        lowered_blob = blob.lower()
        for brand in _KNOWN_BRANDS:
            if brand in lowered_blob and brand not in sender_domain:
                # Only flag once per email
                signals.append(f"brand_mention_off_domain:{brand}")
                score += 0.15
                break

    score = max(0.0, min(1.0, score))
    return ScamResult(score=score, signals=signals, is_likely_scam=score >= 0.6)
