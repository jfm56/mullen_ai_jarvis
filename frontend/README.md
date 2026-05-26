# Frontend — Jarvis UI

Next.js 15 (App Router) + React 19 + TypeScript + Tailwind. Single-user.
Talks to the FastAPI backend via JWT (issued by `POST /auth/login`).

## Install + run

```powershell
cd F:\Projects\mullen_ai_jarvis\frontend
npm install
npm run dev
```

Open http://localhost:3000.

The backend must be running separately (default `http://127.0.0.1:8000`).
The Next.js dev server includes a CORS pre-flight to that origin; backend
CORS is allow-listed to `http://localhost:3000` and `http://127.0.0.1:3000`
by default — extend via `JARVIS_CORS_ORIGINS` env var on the backend.

## Pages

| Route | Purpose |
|---|---|
| `/` | **Today** — daily plan, open tasks, ask the Personal Assistant (text **or voice** via push-to-talk) |
| `/tasks` | Tasks CRUD |
| `/approvals` | **Pending approvals queue** — every gated agent action lands here; destructive actions require typing the confirmation phrase into the note |
| `/projects` | Active projects across all verticals |
| `/grants` | Grant applications with status + eligibility |
| `/agents` | Generic chat — pick any of the 8 agents, choose permission level |
| `/settings` | Account info + pointer to endpoints not yet in the UI |
| `/login` | Sign-in form |

## Voice

The mic button on `/` records via `MediaRecorder`, uploads to `POST /voice/transcribe`,
feeds the transcript to the Personal Assistant, and (if TTS is configured)
speaks the reply via `POST /voice/speak`. Browser support: Chromium/Firefox
(webm/opus) or Safari 14.1+ (mp4/AAC). HTTPS is required by browsers for
mic access — use `http://localhost` (which counts as a secure origin) or
serve the app behind TLS for production.

For voice to work the backend needs `pip install -e .[voice]` (faster-whisper +
piper-tts) and `JARVIS_PIPER_VOICE_PATH` pointing at a `.onnx` voice model
([voice list](https://github.com/rhasspy/piper#voices)). When voice isn't
configured the mic button shows a graceful "unavailable" message rather than
breaking the page.

## Config

`.env.local` (gitignored):

```
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000
```

## Build

```powershell
npm run build
npm run start
```

## What's intentionally missing from v1

The backend has **109 endpoints across 8 agents + 9 migrations + 236 tests**.
This UI surfaces the highest-leverage operations: today view, tasks, the
approvals queue, projects, grants list, and a generic agent chat. The rest
have working REST APIs and can be exercised via `curl` / Postman / HTTPie:

- Memory controls (list/search/edit/delete + topic disables)
- Opportunity pipeline + proposal drafting workflow
- Email triage UI (list, categorize, draft replies, see scam scores)
- Lead pipeline UI (score, recommend follow-up, draft outreach)
- Social content calendar (drafts, scheduling, suggest topics)
- Computer Control allow-list management + execution surface
- Grant section drafting / assembly / finalize flow
- Backup management UI

See [`docs/AGENTS.md`](../docs/AGENTS.md) for the contract of every agent
and [`docs/ROADMAP.md`](../docs/ROADMAP.md) for the full backend feature
list.

## Conventions

- Server components by default; client components when the page needs state
  (most do — this is a single-page app feel inside App Router).
- `useRequireAuth()` from `@/lib/auth` redirects to `/login` when there's
  no token. Every protected page calls it as the first hook.
- Errors are caught and surfaced inline. No global toast system in v1 —
  the inline error blocks are easier to debug.
- Tailwind utility classes; a few component classes in `globals.css`
  (`.btn-primary`, `.card`, `.pill`, etc.) keep the markup readable.
