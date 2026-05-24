# Agents

Each agent implements `BaseAgent` (see [`backend/app/agents/base.py`](../backend/app/agents/base.py)). This doc is the human-readable contract for what each agent owns, what it must not do, and what data it touches.

## Common contract

Every agent must:

1. Declare its `name`, supported `domains`, and `default_permission_level`.
2. Tag every action it emits with one of the action classes in [SECURITY.md](SECURITY.md).
3. Route all external calls through `app/integrations/*` — never call third-party APIs directly.
4. Read and write memory only through `app/memory/store.py` (which enforces domain isolation).
5. Log every meaningful step through `app/security/audit.py`.
6. Be safe to instantiate multiple times concurrently (no module-level mutable state).

---

## 1. Personal Assistant

**Domains:** `personal`
**Default level:** `ask_before_action`

**Owns:**
- Daily plan / morning brief
- Calendar (Google Calendar via `integrations/google_calendar.py`)
- Tasks and reminders (local DB)
- Family scheduling support
- Voice quick-add ("add a task to call the EMS director")

**Never:**
- Touches business or client domains
- Accepts meeting invites without approval

**First-build target.** See ROADMAP Phase 2.

---

## 2. Email Assistant

**Domains:** `personal`, `business`, `client_*` (per-thread scoping based on sender)
**Default level:** `draft_only`

**Owns:**
- Inbox poll + categorize (urgent / waiting-on-me / FYI / newsletter / suspicious)
- Daily inbox summary
- Draft replies in your voice
- Phishing/scam detection (local rules + classifier, separate from LLM)
- Urgency flagging tuned to your historical responses

**Never:**
- Sends email under any circumstance without an explicit per-message approval
- Reads cross-domain (a personal email's draft can't pull from `client_*` memory)

---

## 3. Project Manager

**Domains:** `business`, `client_*`
**Default level:** `ask_before_action`

**Owns:**
- Active project list across business/school/grant/drone/EMS/healthcare/AI consulting
- Task lists and deadline tracking
- Progress summaries and weekly status reports
- Project notes and meeting decisions

**Never:**
- Notifies clients about status changes without approval (drafts only)

---

## 4. Marketing

**Domains:** `business`, `public`
**Default level:** `draft_only`

**Owns:**
- Social post drafts for verticals: healthcare, EMS, fire/public safety, drone analytics, AI consulting
- Content calendar
- Campaign ideation
- Engagement tracking (manual paste-in initially)
- Style guide adherence (learned from approved posts)

**Never:**
- Posts to any platform automatically — always queues for approval with preview
- Pulls from `personal` or `client_*` data without explicit grant (avoids accidentally exposing client work in a public post)

---

## 5. Lead Generation

**Domains:** `business`
**Default level:** `ask_before_action`

**Owns:**
- Prospect research (web + manual seeds)
- Lead scoring against your ideal-customer profile
- Outreach draft generation
- Follow-up cadence recommendation
- Pipeline status (researched → contacted → meeting → proposal → won/lost)

**Never:**
- Contacts a lead directly — always drafts and queues
- Scrapes sites that disallow it; respects robots.txt

---

## 6. Business Development

**Domains:** `business`
**Default level:** `ask_before_action`

**Owns:**
- Grants, RFPs, contracts, partnership opportunities watch list
- Proposal drafting (pulls from past wins + project bios)
- Outreach plans for partnership conversations
- CRM-style opportunity pipeline

**Never:**
- Submits a proposal or application without explicit approval (action.external_send)

---

## 7. Computer Control

**Domains:** any, but level is per-domain
**Default level:** `read_only`

**Owns:**
- Launch allow-listed apps
- File search and organization (read-only by default)
- Run scripts from `scripts/approved/` (hash-checked)
- Browser sessions via Playwright (dedicated profile)
- Repetitive admin automation

**Never:**
- Runs an arbitrary shell command (everything goes through the integration layer's allow-list)
- Modifies system settings, registry, services, or installs software without `admin` + typed confirmation
- Deletes files without approval, ever

**Build phase:** last. Gated on Phases 1+2 being solid. See ROADMAP Phase 7.

---

## Inter-agent coordination

Agents don't call each other directly. They publish "intents" to a small in-process bus that the API layer can route. Examples:

- Email Assistant categorizes an email as "lead inquiry" → publishes intent → Lead Generation Agent picks it up to draft a response.
- Project Manager sees a project hitting a deadline → publishes intent → Personal Assistant adds a reminder to your calendar.

The bus is in-process for v1 (no Redis pub/sub needed). Every cross-agent intent is audited.
