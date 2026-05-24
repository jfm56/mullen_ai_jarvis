# Architecture

## Guiding principles

1. **Local-first.** Sensitive data (emails, calendar, client info, business documents) is processed by local models. Cloud LLMs are only invoked for explicitly non-sensitive tasks (e.g., generic marketing copy with no PII).
2. **Human-in-the-loop by default.** Any externally visible action — sending, posting, contacting, paying, deleting, modifying shared documents — requires explicit approval. The system can draft and queue, but never autonomously commit.
3. **Separation of concerns by data domain.** Personal, business (Mullen Analytics & AI Consulting), and per-client data are stored in logically separated namespaces with independent access policies.
4. **Auditable.** Every agent action, model call, integration call, and approval decision is written to an append-only audit log.
5. **Pluggable agents.** Each agent implements a common `BaseAgent` contract so they can be added, removed, or sandboxed independently.

## Stack

| Layer | Choice | Rationale |
|---|---|---|
| API | FastAPI | Async, typed, easy WebSocket support for voice + streaming |
| ORM | SQLAlchemy 2.x + Alembic | Mature, async-capable, plays well with pgvector |
| DB | PostgreSQL 16 + pgvector | One store for relational + vector; backups are one job |
| Vector memory | pgvector | Co-located with relational data, no separate Pinecone/Chroma to operate |
| Task queue | RQ (Redis Queue) | Lighter than Celery; sufficient for single-user assistant |
| Local LLM | Ollama | Easy model swaps; runs on local GPU/CPU |
| Cloud LLM (optional) | Anthropic / OpenAI | Only for explicitly non-sensitive tasks |
| STT | Whisper (local, faster-whisper) | Private, accurate, offline-capable |
| TTS | Piper or Coqui (local) | Private, low latency |
| Secrets | `keyring` → Windows Credential Manager | OS-native, no plaintext on disk |
| Frontend | Next.js (App Router) + Tailwind | Single SPA that can later wrap in Tauri/Electron for desktop |
| Browser automation | Playwright | When the Computer Control Agent needs to drive web apps |

## Logical structure

```
┌───────────────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                           │
│  Chat UI · Voice · Inbox · Calendar · Pipeline · Approvals    │
└───────────────────────────────┬───────────────────────────────┘
                                │ HTTPS / WebSocket
┌───────────────────────────────▼───────────────────────────────┐
│  FastAPI (app/main.py)                                        │
│  Routes → Agent Router → BaseAgent.handle()                   │
└────┬──────────┬──────────┬──────────┬──────────┬──────────────┘
     │          │          │          │          │
┌────▼────┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────────┐
│ Agents  │ │ Memory │ │ Secrets│ │ Audit  │ │Permissions │
│ (7)     │ │(pgvec) │ │(keyring│ │ log    │ │  engine    │
└────┬────┘ └────────┘ └────────┘ └────────┘ └────────────┘
     │
┌────▼────────────────────────────────────────────────────────┐
│  Integrations: Gmail · Calendar · Drive · LinkedIn ·        │
│  Facebook · X · GitHub · Local FS / Apps (gated)            │
└─────────────────────────────────────────────────────────────┘
                                ▲
                                │
┌───────────────────────────────┴────────┐
│  Local LLM (Ollama) · Optional Cloud   │
└────────────────────────────────────────┘
```

## Request flow

1. User speaks or types a request.
2. STT (if voice) → text → frontend posts to `/api/agent/<name>/handle`.
3. Permission engine checks the agent's current level and the action's risk class.
4. Agent assembles context: prompts + relevant memories (pgvector top-k) + integration data.
5. Agent calls LLM (local by default; cloud only if action is tagged `non_sensitive`).
6. If the action is **draft-class** (writes to local DB only) it executes. If **action-class** (sends/posts/deletes/spends) the response is queued in the Approvals table and surfaced in the UI.
7. User reviews queued action → approves or rejects → executor runs the integration call → audit row written.

## Memory model

- **Short-term:** per-conversation message buffer (Postgres, expires).
- **Episodic:** every interaction, action, and approval is embedded and stored with metadata `{domain: personal|business|client_<id>, scope, timestamp}`.
- **Semantic:** distilled facts the user has confirmed (writing style, preferences, contact relationships, project briefs).
- **Procedural:** approved workflows the assistant can re-run (e.g., "draft weekly EMS LinkedIn post").

Memory is queried by domain — the Email Assistant working on a client thread can pull from `client_<id>` and `business`, but not from `personal` unless explicitly granted.

## Why these choices over alternatives

- **pgvector over Chroma/Pinecone:** one database to back up, one set of credentials, transactional consistency between memory and relational state.
- **RQ over Celery:** Celery's broker/result-backend complexity isn't justified for a single-user system.
- **Ollama over llama.cpp directly:** simpler model management; the API is stable.
- **Next.js over a SwiftUI/native shell:** keeps the door open for browser/PWA usage; can still package as desktop via Tauri later.
- **Keyring over an encrypted vault file:** OS-managed key material, no master-password UX to design, integrates with Windows Hello.

## Open questions (defer)

- Multi-device sync — currently single workstation. If a second machine is needed, prefer encrypted backup/restore over live sync.
- Mobile companion — out of scope for v1; consider Twilio SMS bridge or a small read-only PWA.
- Local model size — start with `llama3.1:8b`; revisit when we measure agent quality.
