"""Health / index endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app import __version__

router = APIRouter(tags=["health"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> str:
    """A tiny landing page so opening http://127.0.0.1:8000 in a browser
    isn't a confusing 404. Lists the obvious pointers."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Jarvis API · v{__version__}</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, sans-serif;
           max-width: 640px; margin: 4rem auto; padding: 0 1rem;
           color: #1d2e39; line-height: 1.5; }}
    h1 {{ font-size: 1.25rem; margin: 0 0 0.5rem; }}
    p, li {{ font-size: 0.95rem; }}
    code {{ background: #eef; padding: 0.05rem 0.3rem; border-radius: 3px;
            font-size: 0.85rem; }}
    a {{ color: #3a5566; }}
    .muted {{ color: #5b7a8f; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <h1>mullen_ai_jarvis API · v{__version__}</h1>
  <p>The backend is running. This page exists so opening the API root in a
     browser isn't a 404.</p>
  <ul>
    <li><a href="/docs">/docs</a> — interactive Swagger UI for all 110+ endpoints</li>
    <li><a href="/redoc">/redoc</a> — alternate API browser</li>
    <li><a href="/healthz">/healthz</a> — liveness probe</li>
    <li><a href="/openapi.json">/openapi.json</a> — raw OpenAPI schema</li>
  </ul>
  <p class="muted">The user-facing UI lives separately at
     <code>http://localhost:3000</code> (run <code>npm run dev</code> in
     <code>frontend/</code>).</p>
</body>
</html>
"""


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
