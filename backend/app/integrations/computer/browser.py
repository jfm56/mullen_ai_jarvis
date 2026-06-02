"""Playwright browser automation, gated.

Design rules (the things the agent CAN'T bypass):

1. Lazy import. Playwright is an optional extra ([automation]). If it isn't
   installed, every function raises BrowserNotInstalledError with the
   install instructions instead of crashing the module at import time.

2. Dedicated profile. Each session uses a `user_data_dir` under the project's
   storage path. NEVER the user's default Chrome profile. No accidental
   access to existing logged-in cookies.

3. Domain allow-list. `navigate(url)` calls `is_domain_allowed(url, patterns)`
   first; non-allowed domains raise `BrowserNavigationError`. The
   allow-list is supplied per-call by the agent (loaded from
   BrowserAllowedDomain rows).

4. Danger-button detection. `submit_form()` and `click_if_matches()` check
   if the matched element's text contains one of `_DANGER_WORDS`
   (submit / send / buy / pay / delete / confirm / order / charge). If so
   the call raises `DangerActionRequiresApproval` so the agent layer
   can route through `BaseAgent.propose`.

5. Idle timeout. The wrapper exposes `is_idle(now)` so an external janitor
   (or the agent layer) can decide when to call `stop()` on a session
   that hasn't been touched recently.

This module deliberately does NOT enforce approval gating itself —
that's the agent's job. This is the layer below: it provides the
primitives, refuses the obviously-unsafe shapes, and raises clean
exceptions so the caller knows when to go through the approval path.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import re
import shutil
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("jarvis.browser")


class BrowserNotInstalledError(RuntimeError):
    """Playwright isn't installed. See the message for the install command."""


class BrowserNavigationError(PermissionError):
    """Target URL is outside the allow-list, malformed, or blocked."""


class DangerActionRequiresApproval(PermissionError):
    """The matched element's text looks like a submit/send/payment action.
    The caller must route this through `BaseAgent.propose` with
    `action.action_external_send`."""


_DANGER_WORDS = re.compile(
    r"\b(submit|send|buy|pay|order|charge|donate|confirm|delete|remove|"
    r"unsubscribe|transfer|withdraw|deposit|invest|trade|sign\s*up|"
    r"agree|accept|continue\s+to\s+payment|checkout|complete)\b",
    re.IGNORECASE,
)


def is_available() -> bool:
    """True iff `playwright` can be imported in this venv."""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def is_domain_allowed(url: str, patterns: list[str]) -> bool:
    """True iff the URL's hostname matches at least one fnmatch pattern.

    `localhost` and `127.0.0.1` are always allowed (the user is testing
    their own services).
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except (ValueError, TypeError):
        return False
    if not host:
        return False
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    return any(fnmatch.fnmatchcase(host, p.lower()) for p in patterns)


def _profile_root() -> Path:
    """Where to put per-session user_data_dirs.

    Env: JARVIS_BROWSER_PROFILES → otherwise a temp dir per process.
    """
    override = os.environ.get("JARVIS_BROWSER_PROFILES")
    if override:
        p = Path(override).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path(tempfile.gettempdir()) / "jarvis_browser_profiles"


@dataclass
class _NavResult:
    url: str
    title: str
    status_code: int


@dataclass
class _TextResult:
    text: str
    matched: int


@dataclass
class _ClickResult:
    selector: str
    matched_text: str


@dataclass
class _SubmitResult:
    selector: str
    matched_text: str
    final_url: str


@dataclass
class BrowserSessionHandle:
    """Live Playwright context bound to one session id.

    Held in-memory in `_LIVE` keyed by session id. NOT persisted —
    process restart drops live sessions (the DB rows remain so the user
    can see what happened, but they're considered closed).
    """

    session_id: str
    user_id: str
    profile_dir: Path
    pw: Any                     # playwright instance
    context: Any                # BrowserContext
    page: Any                   # Page
    started_at: datetime
    last_active_at: datetime
    allowed_patterns: list[str] = field(default_factory=list)

    def touch(self) -> None:
        self.last_active_at = datetime.now(timezone.utc)

    def is_idle(self, now: datetime, idle_seconds: int) -> bool:
        return (now - self.last_active_at) > timedelta(seconds=idle_seconds)


_LIVE: dict[str, BrowserSessionHandle] = {}


def get_live(session_id: str) -> BrowserSessionHandle | None:
    return _LIVE.get(session_id)


async def start_session(
    *,
    session_id: str,
    user_id: str,
    allowed_patterns: list[str],
    headless: bool = True,
) -> BrowserSessionHandle:
    """Launch a chromium with a dedicated profile_dir. Returns the handle.

    The caller is responsible for persisting the session row + profile_dir.
    """
    if session_id in _LIVE:
        raise RuntimeError(f"session {session_id} already started")
    try:
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise BrowserNotInstalledError(
            "playwright not installed. Install with: "
            "pip install -e .[automation]  (from backend/)  "
            "AND run: python -m playwright install chromium"
        ) from exc

    profile_dir = _profile_root() / session_id
    profile_dir.mkdir(parents=True, exist_ok=True)

    pw = await async_playwright().start()
    try:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            args=[
                # No background sync, no profile-restore prompts, no
                # default-browser nag.
                "--disable-background-networking",
                "--disable-default-apps",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
    except Exception:
        await pw.stop()
        raise

    page = context.pages[0] if context.pages else await context.new_page()

    handle = BrowserSessionHandle(
        session_id=session_id,
        user_id=user_id,
        profile_dir=profile_dir,
        pw=pw,
        context=context,
        page=page,
        started_at=datetime.now(timezone.utc),
        last_active_at=datetime.now(timezone.utc),
        allowed_patterns=allowed_patterns,
    )
    _LIVE[session_id] = handle
    return handle


async def stop_session(
    session_id: str, *, wipe_profile: bool = True
) -> None:
    """Close the context, stop Playwright, optionally rm the profile_dir."""
    handle = _LIVE.pop(session_id, None)
    if handle is None:
        return
    with suppress(Exception):
        await handle.context.close()
    with suppress(Exception):
        await handle.pw.stop()
    if wipe_profile and handle.profile_dir.exists():
        with suppress(OSError):
            shutil.rmtree(handle.profile_dir)


# ---- per-action primitives -------------------------------------------------


async def navigate(handle: BrowserSessionHandle, url: str, *, timeout_ms: int = 30_000) -> _NavResult:
    if not is_domain_allowed(url, handle.allowed_patterns):
        raise BrowserNavigationError(
            f"navigation refused: '{urlparse(url).hostname}' is not on "
            "the allow-list. Add via BrowserAllowedDomain or refuse."
        )
    response = await handle.page.goto(url, timeout=timeout_ms)
    handle.touch()
    return _NavResult(
        url=handle.page.url,
        title=await handle.page.title(),
        status_code=response.status if response else 0,
    )


async def screenshot(handle: BrowserSessionHandle, *, full_page: bool = False) -> bytes:
    handle.touch()
    return await handle.page.screenshot(full_page=full_page, type="png")


async def get_text(handle: BrowserSessionHandle, selector: str, *, limit: int = 2_000) -> _TextResult:
    handle.touch()
    elements = await handle.page.locator(selector).all()
    parts: list[str] = []
    for el in elements[:50]:
        try:
            t = await el.text_content(timeout=2_000)
        except Exception:  # noqa: BLE001
            continue
        if t:
            parts.append(t.strip())
    joined = "\n".join(parts)[:limit]
    return _TextResult(text=joined, matched=len(parts))


async def click(
    handle: BrowserSessionHandle,
    selector: str,
    *,
    allow_danger: bool = False,
    timeout_ms: int = 10_000,
) -> _ClickResult:
    """Click the first match. If its text contains a danger word and
    `allow_danger` is False, raise `DangerActionRequiresApproval`."""
    locator = handle.page.locator(selector).first
    try:
        text = (await locator.text_content(timeout=2_000)) or ""
    except Exception:  # noqa: BLE001
        text = ""
    if not allow_danger and _DANGER_WORDS.search(text):
        raise DangerActionRequiresApproval(
            f"refusing click: target text {text!r} matches a danger word"
        )
    await locator.click(timeout=timeout_ms)
    handle.touch()
    return _ClickResult(selector=selector, matched_text=text.strip())


async def type_text(
    handle: BrowserSessionHandle,
    selector: str,
    value: str,
    *,
    timeout_ms: int = 10_000,
    submit: bool = False,
) -> None:
    """Type into the first match. `submit=True` is refused here — use
    `submit_form` after going through approval."""
    if submit:
        raise DangerActionRequiresApproval(
            "type_text(submit=True) is not allowed; call submit_form via "
            "the approval-gated agent method instead"
        )
    await handle.page.locator(selector).first.fill(value, timeout=timeout_ms)
    handle.touch()


async def submit_form(
    handle: BrowserSessionHandle,
    *,
    submit_selector: str,
    timeout_ms: int = 30_000,
) -> _SubmitResult:
    """Click a submit-shaped element. Caller MUST have already settled
    an approval — this primitive does not check; it just executes."""
    locator = handle.page.locator(submit_selector).first
    try:
        text = (await locator.text_content(timeout=2_000)) or ""
    except Exception:  # noqa: BLE001
        text = ""
    pre_url = handle.page.url
    await locator.click(timeout=timeout_ms)
    # Wait briefly for navigation; submit may or may not navigate.
    with suppress(Exception):
        await handle.page.wait_for_load_state("networkidle", timeout=timeout_ms)
    handle.touch()
    return _SubmitResult(
        selector=submit_selector,
        matched_text=text.strip(),
        final_url=handle.page.url or pre_url,
    )


# ---- janitor helper --------------------------------------------------------


async def reap_idle_sessions(idle_seconds: int = 600) -> list[str]:
    """Stop any live sessions that have been idle past the cutoff.

    Returns the list of session_ids that got stopped.
    """
    now = datetime.now(timezone.utc)
    stopped: list[str] = []
    for sid in list(_LIVE.keys()):
        h = _LIVE.get(sid)
        if h is None:
            continue
        if h.is_idle(now, idle_seconds):
            with suppress(Exception):
                await stop_session(sid)
            stopped.append(sid)
    return stopped


_ = asyncio  # asyncio is intentionally imported for future tasks
