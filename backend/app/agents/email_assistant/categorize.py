"""Email categorizer.

Uses the local LLM with a constrained-output prompt. If the LLM is down
or returns garbage, falls back to a deterministic heuristic so the inbox
is never left fully uncategorized.

The categorizer is separate from the scam detector — they answer
different questions. A scam email is also a category ("suspicious"),
but the scam detector runs first and unconditionally so the user sees
the scam signals even on borderline cases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.db.models import EmailCategory
from app.integrations import ollama

_VALID = {c.value for c in EmailCategory}

_SYSTEM_PROMPT = """You categorize emails for Jim Mullen's inbox.
Jim runs Mullen Analytics & AI Consulting (healthcare/EMS/fire/drone/AI).

Pick EXACTLY ONE category from this list and respond with only the category name on a single line, nothing else:
- urgent          (needs action today; deadlines; angry customers)
- waiting_on_me   (someone is waiting for Jim's reply or decision)
- fyi             (informational; no action required)
- newsletter      (mailing lists, marketing, digests)
- suspicious      (likely scam/phishing — but the scam detector handles this; only pick if obvious)
- lead_inquiry    (potential client reaching out about Mullen Analytics services)
- internal        (within Mullen Analytics team)
- personal        (family, friends, personal accounts)

If unclear, prefer "fyi". Never explain. Never use Markdown. Just one word.
"""

_NEWSLETTER_HINTS = re.compile(
    r"(unsubscribe|newsletter|view in browser|digest|weekly roundup|monthly update)",
    re.IGNORECASE,
)
_LEAD_HINTS = re.compile(
    r"\b(quote|proposal|consulting|services|engage|partnership|RFP|RFQ|"
    r"interested in|reach(ing)? out about|inquiry|inquir(?:y|ies))\b",
    re.IGNORECASE,
)


@dataclass
class CategorizeResult:
    category: EmailCategory
    confidence: float  # 1.0 when LLM responded with a valid category; 0.4 on fallback
    via: str  # 'llm' or 'fallback'


def _fallback(subject: str, body_text: str, from_addr: str) -> EmailCategory:
    blob = f"{subject}\n{body_text}".lower()
    if _NEWSLETTER_HINTS.search(blob):
        return EmailCategory.newsletter
    if _LEAD_HINTS.search(blob):
        return EmailCategory.lead_inquiry
    if "@mullenanalytics" in from_addr.lower():
        return EmailCategory.internal
    return EmailCategory.fyi


async def categorize(
    *,
    subject: str,
    body_text: str,
    from_addr: str = "",
    model: str | None = None,
) -> CategorizeResult:
    fallback_cat = _fallback(subject, body_text, from_addr)

    prompt = (
        f"From: {from_addr}\nSubject: {subject}\n\n"
        f"{body_text[:2000]}\n\n---\nCategory:"
    )

    try:
        result = await ollama.generate(prompt, system=_SYSTEM_PROMPT, model=model)
    except ollama.OllamaError:
        return CategorizeResult(category=fallback_cat, confidence=0.4, via="fallback")

    answer = result.text.strip().splitlines()[0].strip().lower() if result.text.strip() else ""
    answer = answer.split()[0] if answer else ""

    if answer in _VALID:
        return CategorizeResult(category=EmailCategory(answer), confidence=1.0, via="llm")
    return CategorizeResult(category=fallback_cat, confidence=0.4, via="fallback")
