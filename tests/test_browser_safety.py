"""Browser Control safety primitives — domain allow-list + danger detection.

These tests cover the pure-Python logic without needing Playwright installed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.integrations.computer import browser as pw


# ---- domain allow-list ----------------------------------------------------


def test_localhost_always_allowed() -> None:
    assert pw.is_domain_allowed("http://localhost:3000/", []) is True
    assert pw.is_domain_allowed("http://127.0.0.1:8080/", []) is True


def test_exact_match() -> None:
    assert pw.is_domain_allowed("https://github.com/jfm56", ["github.com"]) is True


def test_subdomain_pattern() -> None:
    assert pw.is_domain_allowed(
        "https://api.github.com/users/x", ["*.github.com"]
    ) is True


def test_unrelated_domain_rejected() -> None:
    assert pw.is_domain_allowed(
        "https://evil.example.com/", ["github.com", "google.com"]
    ) is False


def test_lookalike_not_allowed_by_substring() -> None:
    # githUb.com.evil.tld should NOT match 'github.com'
    assert pw.is_domain_allowed(
        "https://github.com.evil.tld/", ["github.com"]
    ) is False


def test_malformed_url_rejected() -> None:
    assert pw.is_domain_allowed("not-a-url", ["*.example.com"]) is False
    assert pw.is_domain_allowed("", ["*"]) is False


def test_empty_allowlist_blocks_external() -> None:
    assert pw.is_domain_allowed("https://example.com", []) is False


# ---- danger-word detection -------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Submit",
        "Send Message",
        "Buy now",
        "Pay $50",
        "Place Order",
        "Confirm purchase",
        "Delete account",
        "Continue to payment",
        "Checkout",
        "Complete",
        "Sign up",
    ],
)
def test_danger_words_match(text: str) -> None:
    assert pw._DANGER_WORDS.search(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "Read more",
        "Cancel",
        "Back",
        "Search",
        "Filter",
        "Sort by name",
        "Help",
        "About us",
        "Next page",
    ],
)
def test_safe_words_dont_match(text: str) -> None:
    assert pw._DANGER_WORDS.search(text) is None


# ---- session idle helpers --------------------------------------------------


def test_handle_idle_after_threshold() -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    handle = pw.BrowserSessionHandle(
        session_id="s1",
        user_id="u1",
        profile_dir=__import__("pathlib").Path("/tmp/x"),
        pw=None,
        context=None,
        page=None,
        started_at=now - timedelta(hours=2),
        last_active_at=now - timedelta(minutes=15),
    )
    # 15 min idle > 10 min cutoff
    assert handle.is_idle(now, 600) is True
    # 15 min idle < 20 min cutoff
    assert handle.is_idle(now, 1200) is False


def test_handle_touch_resets_idle() -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    handle = pw.BrowserSessionHandle(
        session_id="s1",
        user_id="u1",
        profile_dir=__import__("pathlib").Path("/tmp/x"),
        pw=None,
        context=None,
        page=None,
        started_at=now - timedelta(hours=2),
        last_active_at=now - timedelta(hours=1),
    )
    assert handle.is_idle(now, 600) is True
    handle.touch()
    assert handle.is_idle(now, 600) is False


# ---- not-installed graceful path ------------------------------------------


@pytest.mark.asyncio
async def test_start_session_raises_when_playwright_missing(monkeypatch) -> None:
    """If `playwright` import fails, BrowserNotInstalledError surfaces
    with the install command."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright.async_api" or name.startswith("playwright.async_api"):
            raise ImportError("simulated missing playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(pw.BrowserNotInstalledError) as exc:
        await pw.start_session(
            session_id="s-missing",
            user_id="u",
            allowed_patterns=["example.com"],
        )
    assert "pip install" in str(exc.value)


# ---- navigate refuses off-allowlist domains -------------------------------


@pytest.mark.asyncio
async def test_navigate_refuses_off_allowlist() -> None:
    handle = pw.BrowserSessionHandle(
        session_id="s2",
        user_id="u",
        profile_dir=__import__("pathlib").Path("/tmp/x"),
        pw=None,
        context=SimpleNamespace(),
        page=SimpleNamespace(goto=lambda *a, **k: asyncio.sleep(0)),
        started_at=datetime.now(timezone.utc),
        last_active_at=datetime.now(timezone.utc),
        allowed_patterns=["github.com"],
    )
    with pytest.raises(pw.BrowserNavigationError):
        await pw.navigate(handle, "https://evil.example.com/exfiltrate")


@pytest.mark.asyncio
async def test_click_danger_word_raises(monkeypatch) -> None:
    """A button whose text says 'Buy Now' must not click without approval."""
    class FakeLocator:
        first = None

        def __init__(self): pass

        async def text_content(self, timeout=2000):
            return "Buy Now"

        async def click(self, timeout=2000):
            pytest.fail("should not have clicked — danger word should have raised")

    fl = FakeLocator()
    fl.first = fl  # locator(...).first returns the same fake

    page = SimpleNamespace(locator=lambda sel: fl)
    handle = pw.BrowserSessionHandle(
        session_id="s3",
        user_id="u",
        profile_dir=__import__("pathlib").Path("/tmp/x"),
        pw=None,
        context=SimpleNamespace(),
        page=page,
        started_at=datetime.now(timezone.utc),
        last_active_at=datetime.now(timezone.utc),
        allowed_patterns=["*"],
    )
    with pytest.raises(pw.DangerActionRequiresApproval):
        await pw.click(handle, "button.cta")


@pytest.mark.asyncio
async def test_click_allow_danger_bypasses(monkeypatch) -> None:
    """When `allow_danger=True`, the click goes through. Caller must have
    settled an approval before getting here."""
    clicked = {"value": False}

    class FakeLocator:
        first = None
        def __init__(self): pass
        async def text_content(self, timeout=2000):
            return "Submit"
        async def click(self, timeout=2000):
            clicked["value"] = True

    fl = FakeLocator()
    fl.first = fl

    page = SimpleNamespace(locator=lambda sel: fl)
    handle = pw.BrowserSessionHandle(
        session_id="s4",
        user_id="u",
        profile_dir=__import__("pathlib").Path("/tmp/x"),
        pw=None,
        context=SimpleNamespace(),
        page=page,
        started_at=datetime.now(timezone.utc),
        last_active_at=datetime.now(timezone.utc),
        allowed_patterns=["*"],
    )
    await pw.click(handle, "button.submit", allow_danger=True)
    assert clicked["value"] is True
