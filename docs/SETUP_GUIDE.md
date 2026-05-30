# Setup guide — turn on the rest of the system

The app boots and you can log in. This guide covers the three external
dependencies that unlock real functionality:

1. **Ollama model** — so the agents give real LLM answers instead of the deterministic fallback.
2. **Google OAuth** — so Gmail + Calendar actually have data to read.
3. **Redis + RQ worker** — so background syncs run automatically.

Do them in order. Each section is independent of the next; you can stop after #1 if you want.

---

## 1. Ollama model (5 minutes)

You should already see `ollama call failed` in agent responses. That means Ollama is running but the model isn't pulled. From any terminal:

```powershell
ollama pull llama3.1:8b
```

~5 GB download. After it finishes, send another agent prompt — you'll get a real response. No restart needed.

Optional embedding model for memory (Phase 3 features):
```powershell
ollama pull nomic-embed-text
```

---

## 2. Google OAuth — Gmail + Calendar (15–30 minutes)

You need a Google Cloud project with OAuth credentials. One-time setup.

### 2a. Google Cloud Console

1. Go to https://console.cloud.google.com/ and create a project (name: `jarvis-local`).
2. **APIs & Services → Library** — enable:
   - Gmail API
   - Google Calendar API
3. **APIs & Services → OAuth consent screen**:
   - User type: **External** (the only option without a Workspace).
   - App name: `Jarvis`. User support email: yours.
   - Scopes: skip on this screen (we declare them per-request).
   - Test users: add your own Google address. While in "Testing" mode only test users can authorize, which is what we want.
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Web application**.
   - Authorized redirect URIs: add `http://127.0.0.1:8000/auth/google/callback` (and `http://127.0.0.1:8080/auth/google/callback` if you run on 8080).
   - Save — you'll get a **Client ID** and **Client secret**. Keep the secret tab open.

### 2b. Configure the backend

In `F:\Projects\mullen_ai_jarvis\.env`:

```
GOOGLE_OAUTH_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
GOOGLE_OAUTH_REDIRECT=http://127.0.0.1:8080/auth/google/callback
```

Store the client secret in the Windows keyring (NOT in `.env` for prod-style hygiene):

```powershell
cd F:\Projects\mullen_ai_jarvis\backend
.venv\Scripts\Activate.ps1
python -c "from app.security.secrets import set_secret; set_secret('google_oauth_client_secret', 'PASTE-SECRET-HERE')"
```

Restart uvicorn so the new env vars are picked up.

### 2c. Run the consent flow

While logged into the UI (so the JWT cookie is set), visit in the browser:

```
http://127.0.0.1:8080/auth/google/start?service=gmail
```

You'll be redirected to Google → approve the requested scopes → land back on a "Connected" page. The refresh token is now in your keyring; an `OAuthAccount` row exists.

Repeat for Calendar:
```
http://127.0.0.1:8080/auth/google/start?service=calendar
```

### 2d. Pull data manually (or skip to step 3 for auto)

In the API docs (http://127.0.0.1:8080/docs) try:

- `POST /emails/sync` — body: `{"account_email": "you@gmail.com", "days": 7}`
- `POST /calendar/sync` — body: `{"account_email": "you@gmail.com", "days_back": 1, "days_forward": 30}`

After a successful sync, refresh the Today page (calendar events) or check `/emails` (inbox).

---

## 3. Redis + RQ worker (10 minutes)

This makes #2's sync run automatically every 15 minutes plus fires due reminders every minute.

### 3a. Install Redis on Windows

Options, easiest first:

- **Memurai** — Redis-compatible Windows service: https://www.memurai.com/get-memurai (free Developer Edition).
- **WSL** — `wsl --install`, then in Ubuntu: `sudo apt-get install redis-server && sudo service redis-server start`.
- **Docker Desktop** — `docker run -d --name redis -p 6379:6379 redis:7-alpine`.

Verify with:
```powershell
& "C:\Program Files\Memurai\memurai-cli.exe" ping   # if you used Memurai
# OR
redis-cli ping
# Should print: PONG
```

### 3b. Start the worker + scheduler

Two more terminals (in addition to uvicorn and `npm run dev`):

```powershell
# Terminal 3 — worker
cd F:\Projects\mullen_ai_jarvis\backend
.venv\Scripts\Activate.ps1
python -m app.tasks.worker
```

```powershell
# Terminal 4 — scheduler
cd F:\Projects\mullen_ai_jarvis\backend
.venv\Scripts\Activate.ps1
python -m app.tasks.scheduler
```

The scheduler tick interval defaults to 900s (15 min). For faster dev:
```powershell
$env:JARVIS_SCHEDULER_INTERVAL_S = "60"
```

---

## You should now have

| Component | Window | Verify |
|---|---|---|
| Backend | 1 | `http://localhost:8080/healthz` → 200 |
| Frontend | 2 | `http://localhost:3100` → login screen |
| RQ worker | 3 | log line "RQ worker listening" |
| Scheduler | 4 | log line "scheduler tick complete" every interval |

With Ollama models pulled, Google connected, and the worker+scheduler running, the system is fully live. The Today view shows real calendar events; the Email Assistant has a real inbox to triage; reminders fire automatically.

## Troubleshooting

- **"GOOGLE_OAUTH_CLIENT_ID env var not set"** — restart uvicorn after editing `.env`.
- **"google_oauth_client_secret not in keyring"** — re-run the `python -c "...set_secret..."` line.
- **"Google did not return a refresh_token"** on first connect — revoke at https://myaccount.google.com/permissions then retry. Google only returns the refresh token on *first* consent.
- **Worker can't reach Redis** — Memurai not started, or `REDIS_URL` env points somewhere else.
- **Sync syncs 0 messages** — token works but `q=in:inbox newer_than:7d` returned nothing. Try `days=30`.
