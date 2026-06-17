"""Web search for lead discovery — provider-abstracted.

Default provider is **DuckDuckGo** via the `ddgs` package (no API key, works
out of the box). If `JARVIS_SEARCH_API_KEY` is set, a real search API is used
instead (`JARVIS_SEARCH_PROVIDER` = `tavily` | `brave`) for better quality and
stability.

Lazy imports throughout so a missing optional dependency raises a clear,
actionable error instead of crashing the module at import time (mirrors the
voice/automation integrations).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass


class WebSearchError(RuntimeError):
    """Search failed (network, provider error, or missing dependency)."""


class WebSearchNotInstalled(WebSearchError):
    """The selected provider's client library isn't installed."""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def active_provider() -> str:
    """Which provider will be used given the current env."""
    if os.environ.get("JARVIS_SEARCH_API_KEY"):
        return os.environ.get("JARVIS_SEARCH_PROVIDER", "tavily").strip().lower()
    return "duckduckgo"


async def search(query: str, *, max_results: int = 8) -> list[SearchResult]:
    """Run one web search and return normalized results.

    Never raises for "no results" — returns an empty list. Raises
    WebSearchError only on a genuine provider/transport failure.
    """
    provider = active_provider()
    if provider == "tavily":
        return await _tavily(query, max_results)
    if provider == "brave":
        return await _brave(query, max_results)
    return await _duckduckgo(query, max_results)


async def _duckduckgo(query: str, max_results: int) -> list[SearchResult]:
    def _run() -> list[SearchResult]:
        try:
            from ddgs import DDGS  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - install-path guard
            raise WebSearchNotInstalled(
                "ddgs not installed. Install with: pip install -e .[discovery]  (from backend/)"
            ) from exc
        out: list[SearchResult] = []
        try:
            for r in DDGS().text(query, max_results=max_results):
                out.append(
                    SearchResult(
                        title=r.get("title", "") or "",
                        url=r.get("href", "") or "",
                        snippet=r.get("body", "") or "",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - ddgs raises assorted runtime errors
            raise WebSearchError(f"duckduckgo search failed: {exc}") from exc
        return out

    # ddgs is synchronous + blocking — keep it off the event loop.
    return await asyncio.to_thread(_run)


async def _tavily(query: str, max_results: int) -> list[SearchResult]:
    import httpx

    key = os.environ["JARVIS_SEARCH_API_KEY"]
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise WebSearchError(f"tavily search failed: {exc}") from exc
    return [
        SearchResult(
            title=x.get("title", "") or "",
            url=x.get("url", "") or "",
            snippet=x.get("content", "") or "",
        )
        for x in data.get("results", [])
    ]


async def _brave(query: str, max_results: int) -> list[SearchResult]:
    import httpx

    key = os.environ["JARVIS_SEARCH_API_KEY"]
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        ) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise WebSearchError(f"brave search failed: {exc}") from exc
    results = (data.get("web") or {}).get("results", [])
    return [
        SearchResult(
            title=x.get("title", "") or "",
            url=x.get("url", "") or "",
            snippet=x.get("description", "") or "",
        )
        for x in results
    ]
