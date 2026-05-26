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

## Getting started (when ready to develop)

```powershell
# From F:\Projects\mullen_ai_jarvis
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
copy ..\.env.example ..\.env  # then fill in
uvicorn app.main:app --reload
```

## Repository layout

```
mullen_ai_jarvis/
├── docs/           Planning, architecture, security, agent contracts
├── backend/        FastAPI app: agents, memory, security, integrations
├── frontend/       Next.js UI (placeholder)
├── scripts/        Bootstrap and operational scripts
└── tests/          Pytest suite
```
