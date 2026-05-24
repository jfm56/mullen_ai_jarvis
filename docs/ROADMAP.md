# Roadmap

A phased plan so each milestone produces something usable instead of half-finished pieces spread across every agent.

## Phase 0 — Scaffold (current)

**Goal:** repo structure, planning docs, no working features.

- [x] Project tree
- [x] Planning docs (ARCHITECTURE, ROADMAP, SECURITY, AGENTS)
- [x] `.env.example`, `.gitignore`
- [x] Backend Python package skeleton with `BaseAgent` contract
- [x] Stubs for all 7 agents
- [ ] Git repo initialized with first commit

**Done when:** `tree` matches the layout in README, every doc reads coherently.

## Phase 1 — Security spine

**Goal:** safety machinery exists before any agent can do anything.

- [ ] `app/security/secrets.py` — `keyring` wrapper with `.env` fallback
- [ ] `app/security/permissions.py` — permission level enum + risk classifier
- [ ] `app/security/audit.py` — append-only audit log (Postgres table + helper)
- [ ] `app/security/auth.py` — single-user auth (password + optional Windows Hello)
- [ ] Approvals queue table + API endpoints (`GET /approvals`, `POST /approvals/{id}/decision`)
- [ ] Pytest: permission denial paths, audit row written for every action

**Done when:** an agent attempting an `action-class` call without approval is blocked and logged.

## Phase 2 — Personal Assistant (first agent)

**Goal:** one agent working end-to-end as a vertical slice. Validates the whole stack.

- [ ] Google Calendar OAuth + read-only sync (events into local DB)
- [ ] Google Calendar write (create events) — gated on approval
- [ ] Tasks table + simple CRUD
- [ ] Daily-planning prompt + Ollama integration
- [ ] Reminders (RQ scheduled jobs)
- [ ] Minimal Next.js page: today view + chat input
- [ ] Voice: Whisper STT → text input; Piper TTS → spoken reply
- [ ] First semantic memories: morning/evening preferences, common task categories

**Done when:** you can say "Jarvis, what do I have today?" and get a useful spoken answer; you can say "remind me to call the EMS director tomorrow at 9" and see an approval-pending reminder.

## Phase 3 — Memory + learning controls

**Goal:** the assistant gets noticeably better with use, and you can inspect/edit what it knows.

- [ ] pgvector tables + embedding pipeline (local model)
- [ ] Memory write-back from approvals (approved/rejected → semantic learning)
- [ ] Memory UI: list, search, edit, delete, disable-topic
- [ ] Domain isolation enforced in queries (personal / business / client_*)

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
