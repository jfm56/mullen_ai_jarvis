# mullen_ai_jarvis

A secure, local-first AI executive assistant for personal life, Mullen Analytics & AI Consulting operations, marketing, lead generation, and computer workflows.

## What it is

A multi-agent system that learns your preferences, writing style, schedule, and business goals over time — while keeping you in control of every externally-visible action (no auto-sent emails, no auto-posted social, no auto-spent money).

## Status

**Phase 0 — Scaffold.** Project structure, planning docs, and security spine are in place. No working agents yet. See [docs/ROADMAP.md](docs/ROADMAP.md) for the build plan.

## Architecture at a glance

- **Backend:** FastAPI (Python) + PostgreSQL + pgvector for memory
- **Frontend:** Next.js (planned, not yet scaffolded)
- **Local AI:** Ollama for sensitive tasks; OpenAI API only for non-sensitive
- **Voice:** Whisper STT + local TTS
- **Task queue:** Celery or RQ (TBD)
- **Secrets:** Windows Credential Manager via `keyring` (prod-style) + `.env` for dev

Full details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Agents

| Agent | Status | Purpose |
|---|---|---|
| Personal Assistant | implemented | Calendar, reminders, tasks, daily planning |
| Email Assistant | implemented | Gmail summarize/draft, scam detection, never auto-send |
| Project Manager | implemented | Track active business/school/grant/drone/EMS/healthcare/AI projects |
| Marketing | implemented | Social drafts for healthcare, EMS, fire/public safety, drone, AI consulting |
| Lead Generation | implemented | Find/score leads, draft outreach, track pipeline |
| Business Development | implemented | RFPs, partnerships, proposals |
| Grant Writer | implemented | Multi-section grant applications (NIH/SAMHSA/HRSA/FEMA AFG/DOJ/state/foundation) with eligibility screening + bundle assembly |
| Computer Control | implemented | Open apps, files, run approved scripts — gated, hash-verified, typed confirmation for destructive ops |

See [docs/AGENTS.md](docs/AGENTS.md) for each agent's contract.

## Safety model

Every agent runs under one of five permission levels: **read-only → draft-only → ask-before-action → approved-automation → admin**. Anything externally visible (email, post, message, money, file deletion, system change) requires explicit approval. See [docs/SECURITY.md](docs/SECURITY.md).

## Getting started

```powershell
# === one-time ===
# 1. Install PostgreSQL 16 + pgvector extension.
#    In psql: CREATE DATABASE jarvis; CREATE EXTENSION vector;
# 2. Install Ollama (https://ollama.com) and pull a model:
#    ollama pull llama3.1:8b
#    ollama pull nomic-embed-text

cd F:\Projects\mullen_ai_jarvis

# Backend
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
copy ..\.env.example ..\.env  # then edit
alembic upgrade head

# Guided init — checks DB, sets backup key in keyring, creates admin user
python -m app.cli init

# === every dev session ===
# Terminal 1: backend
cd F:\Projects\mullen_ai_jarvis\backend
.venv\Scripts\Activate.ps1
python -m app                 # serves http://127.0.0.1:8000

# Terminal 2: frontend
cd F:\Projects\mullen_ai_jarvis\frontend
npm install                  # first time only
npm run dev                  # open http://localhost:3000
```

> **Windows:** start the backend with `python -m app`, **not** `uvicorn app.main:app`
> directly. The async Postgres driver (psycopg) needs a SelectorEventLoop, but the
> bare `uvicorn` CLI builds a ProactorEventLoop before loading the app, so every
> request fails with a 500. `python -m app` sets the right policy first — see
> [`backend/app/__main__.py`](backend/app/__main__.py).

Sign in with the user you created via `app.cli init`. The UI gives you Today,
Tasks, Approvals, Projects, Leads, Grants, Marketing, generic Agent chat, and
Settings.

## Repository layout

```
mullen_ai_jarvis/
├── docs/           Planning, architecture, security, agent contracts
├── backend/        FastAPI app: agents, memory, security, integrations
│   ├── app/        Python package (`pip install -e .`)
│   └── alembic/    Database migrations (9 so far)
├── frontend/       Next.js 15 App Router UI
│   └── src/        TypeScript + Tailwind
├── scripts/        Bootstrap and operational scripts
└── tests/          Pytest suite (236 tests)
```

## Status

All 8 agents implemented end-to-end, 109 API endpoints, 9 migrations,
236 tests passing. See [docs/ROADMAP.md](docs/ROADMAP.md) for what
landed in each phase and what's deferred (voice, live OAuth, Redis worker).
