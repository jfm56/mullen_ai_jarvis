# Roadmap

A phased plan so each milestone produces something usable instead of half-finished pieces spread across every agent.

## Phase 0 — Scaffold ✓

**Goal:** repo structure, planning docs, no working features.

- [x] Project tree
- [x] Planning docs (ARCHITECTURE, ROADMAP, SECURITY, AGENTS)
- [x] `.env.example`, `.gitignore`
- [x] Backend Python package skeleton with `BaseAgent` contract
- [x] Stubs for all 7 agents
- [x] Git repo initialized + pushed to GitHub

## Phase 1 — Security spine ✓

**Goal:** safety machinery exists before any agent can do anything.

- [x] `app/security/secrets.py` — `keyring` wrapper with `.env` fallback
- [x] `app/security/permissions.py` — permission level enum + risk classifier (full level × class matrix tested)
- [x] `app/security/audit.py` — append-only audit log, DB-backed; Postgres trigger blocks UPDATE/DELETE
- [x] `app/security/auth.py` — Argon2id password hashing + JWT sessions, opportunistic rehash
- [x] `app/security/approvals.py` — approvals queue service (create_pending / list_pending / decide / mark_outcome)
- [x] API endpoints: `POST /auth/login`, `GET /auth/me`, `GET /approvals`, `GET /approvals/{id}`, `POST /approvals/{id}/decision`
- [x] `BaseAgent.propose` creates a pending approval row on `require_approval` instead of just auditing
- [x] Alembic + migration `0001_initial_security_spine`
- [x] Pytest: 46 passing — auth round-trip, JWT tampering/expiry, full permission matrix, audit payload hash
- [x] DB-integration test for full approval lifecycle (marked `requires_db`, runs when `JARVIS_TEST_DB_URL` is set)

**Done when:** an agent attempting an `action-class` call without approval is blocked and logged. ✓

## Phase 2 — Personal Assistant (first agent) — backend done, UI + voice deferred

**Goal:** one agent working end-to-end as a vertical slice. Validates the whole stack.

**Backend (this milestone):**
- [x] `Task`, `Reminder`, `CalendarEvent`, `OAuthAccount` models + migration `0002_phase2_personal_assistant`
- [x] Tasks CRUD: `GET/POST /tasks`, `PATCH/DELETE /tasks/{id}`
- [x] Reminders: `GET /reminders`, `GET /reminders/due`, `POST /reminders`, `POST /reminders/{id}/cancel|ack`
- [x] Google Calendar OAuth URL builder + `upsert_event` for idempotent sync
- [x] Ollama HTTP client with graceful error → fallback path in the agent
- [x] `PersonalAssistantAgent.handle()` composes today's events + tasks + reminders, calls LLM, falls back to deterministic summary if LLM is down
- [x] `POST /agents/personal_assistant/handle`
- [x] `app/cli.py create-user` so Phase 1 login is actually usable
- [x] 18 new tests (Ollama mocked, agent with stub deps, Calendar URL builder, CLI smoke) — 64 total passing

**Deferred to an interactive session (needs your hands-on setup):**
- [ ] **Google Calendar live sync** — needs OAuth client created in Google Cloud Console and the client secret loaded into keyring. Code path is built; flip on once credentials exist.
- [ ] **RQ scheduled job for firing reminders** — needs Redis. Until then `/reminders/due` is poll-based and the UI surfaces what's ready.
- [ ] **Minimal Next.js today view** — `create-next-app` ceremony + UI components are better done interactively. The backend serves everything it needs.
- [ ] **Voice: Whisper STT + Piper TTS** — needs `faster-whisper` (heavy install, model download), microphone access for verification. Best to wire up live.
- [ ] **First semantic memories** — folded into Phase 3 (memory subsystem) since the embedding pipeline lives there.

**Done when:** authenticated `POST /agents/personal_assistant/handle` returns a useful summary; tasks and reminders survive a round-trip; calendar events sync once OAuth is provisioned. ✓ (backend portion)

## Phase 3 — Memory + learning controls — backend done, UI deferred

**Goal:** the assistant gets noticeably better with use, and you can inspect/edit what it knows.

**Backend (this milestone):**
- [x] `Memory` model with `Vector(768)` column + `TopicDisable` model; migration `0003_phase3_memory` installs the `vector` extension and an `ivfflat` cosine-similarity index
- [x] `ollama.embed()` calling `/api/embeddings` with `nomic-embed-text` by default
- [x] `app/memory/store.py` with **mandatory-domain** API surface — `write` / `search` / `list_recent` all require `domain=` (verified by signature tests that fail if a default sneaks in)
- [x] Topic-disable substring matching blocks `store.write()` before embedding
- [x] `cross_domain_search()` requires a non-empty `reason`; every call is audited
- [x] Embedding failures don't lose the fact — row stored with `embedding=NULL` for later reindex; search degrades to recency
- [x] `app/memory/learning.py` writes memories from settled approvals:
  - approved → `procedural` memory
  - rejected → `semantic` memory (plus a second one verbatim from the note, if any)
  - hook runs OUTSIDE the approval transaction so embedding hiccups can't roll back the user's decision
  - all failures swallowed (best-effort by design)
- [x] API: `GET /memory?domain=&kind=&q=` (list or semantic search), `GET/PATCH/DELETE /memory/{id}`, `GET/POST /memory/disabled-topics`, `DELETE /memory/disabled-topics/{id}`
- [x] 17 new tests (81 total passing): embedding wrapper edge cases, mandatory-domain signature guards, learning hook for every approval-status branch, error swallowing

**Deferred:**
- [ ] **Memory management UI** — list/search/edit/delete chrome lands with the Next.js scaffold.
- [ ] **Embedding-based topic detection** — current substring match is sufficient for v1. Swap to semantic match without API change.
- [ ] **Reindex job** — fills in `embedding=NULL` rows once Ollama is back. Schedule lands with RQ.

**Done when:** memories survive a round-trip with domain isolation provable by code shape; approving or rejecting an action visibly teaches the assistant. ✓ (backend portion)

## Phase 4 — Email Assistant

**Goal:** safe inbox triage.

- [ ] Gmail OAuth (read-only first, send scope added later behind approval)
- [ ] Inbox poller → embed → categorize
- [ ] Daily inbox summary
- [ ] Draft replies (never sent without approval)
- [ ] Scam/phishing classifier (local model + heuristics)
- [ ] Urgency flagging tuned to your patterns over time

## Phase 5 — Project Manager + Business Development

**Goal:** track Mullen Analytics work, grants, RFPs.

- [ ] Projects table + status taxonomy (active / paused / proposal / won / lost)
- [ ] Grant/RFP watch list (manual seed; later automated discovery)
- [ ] Weekly status report generator
- [ ] Proposal drafting from project context + reference docs

## Phase 6 — Marketing + Lead Generation

**Goal:** content drafts and pipeline tracking. Still nothing posts without approval.

- [ ] Social post drafts by vertical (healthcare / EMS / fire / drone / AI consulting)
- [ ] Content calendar
- [ ] Lead pipeline (research → contacted → meeting → proposal → close)
- [ ] Outreach draft + recommended follow-up cadence
- [ ] Engagement tracking (manual paste-in first; API integrations later)

## Phase 7 — Computer Control Agent

**Goal:** safe local automation. This phase is gated — only start after Phases 1 + 2 are solid.

- [ ] Allow-listed app launcher
- [ ] File search + organize (read-only by default)
- [ ] Approved script runner (signed allow-list)
- [ ] Playwright browser sessions for tedious web tasks
- [ ] Destructive operations require typed confirmation, not just a click

## Phase 8 — Polish

- [ ] Backup + restore (encrypted)
- [ ] Sensitive-data redaction in logs
- [ ] Performance: response time targets, local model warmup
- [ ] Onboarding flow for fresh installs
- [ ] Optional desktop wrapper (Tauri)

## Non-goals (for v1)

- Multi-user / multi-tenant
- Mobile native apps
- Real-time collaboration features
- Replacing existing CRM (it integrates, doesn't replace)
- Auto-posting or auto-sending anything, ever
