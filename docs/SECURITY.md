# Security & Safety Model

This document is normative. If a feature elsewhere conflicts with what's here, the feature is wrong.

## Permission levels

Every agent runs at one of these levels for a given session/domain. The default is `ask_before_action`.

| Level | Can read | Can write to local DB | Can call external integrations | Can take action-class operations |
|---|---|---|---|---|
| `read_only` | yes | no | read-only API calls only | no |
| `draft_only` | yes | yes | read-only API calls only | no |
| `ask_before_action` | yes | yes | read-only API calls only | only after approval per call |
| `approved_automation` | yes | yes | yes, within allow-listed scopes | yes, within pre-approved workflows |
| `admin` | yes | yes | yes | yes (used for system maintenance, not normal operation) |

Levels are per-`(agent, domain)`. The Marketing Agent might be `draft_only` for `business`, while the Personal Assistant is `approved_automation` for `personal` calendar events.

## Action classes

Every operation the system can perform is tagged with a class. The permission engine uses this tag plus the agent's level to decide whether to execute, queue for approval, or reject.

| Class | Examples | Default treatment |
|---|---|---|
| `read` | List calendar events, fetch email headers, read a file | Allowed at all levels |
| `draft` | Save a draft email, create a local task, write to memory | Allowed at `draft_only`+ |
| `action.low_risk` | Create a private calendar event, rename a local file | Approval required (one-tap) |
| `action.external_send` | Send email, post to social, send DM, submit form | Approval required (explicit, with preview) |
| `action.financial` | Spend money, submit invoice, charge a card | Approval required (typed confirmation) |
| `action.destructive` | Delete file, drop DB rows, uninstall software | Approval required (typed confirmation) |
| `action.system` | Change OS settings, modify env vars, install software | Approval required (typed confirmation + audit reason) |

## The "never auto-" list

These operations **never** execute without an explicit, per-instance approval, regardless of permission level (including `admin`):

- Send an email
- Send an SMS, DM, or chat message
- Post publicly on any platform (LinkedIn, Facebook, X, etc.)
- Submit a form, application, or proposal to an external party
- Spend money or initiate any financial transaction
- Contact a client or lead on your behalf
- Delete a file you didn't ask it to delete
- Modify a document outside its own working scratch area
- Change a system setting (registry, services, scheduled tasks, firewall)
- Run a command not on the allow-list
- Grant a new OAuth scope

## Data domains

Memories, documents, and agent context are tagged with a domain. Cross-domain reads require explicit grants.

- `personal` — family, health, personal calendar, personal email
- `business` — Mullen Analytics & AI Consulting operations, internal docs, internal calendar
- `client_<id>` — per-client workspace; isolated by default
- `public` — publicly available reference material (e.g., FCC drone regs)

The Lead Generation Agent working on `client_acme` cannot read `personal` or `client_globex` memories. The Personal Assistant cannot read `client_*` data.

## Authentication

- Single primary user (you). Local password protected by Argon2id.
- Optional second factor: Windows Hello (via `pywin32` Credential UI) for action-class approvals.
- Sessions: short-lived JWT (60 min default) refreshed on activity; revocable from a sessions panel.
- No remote auth surface in v1. The API only binds to `127.0.0.1`.

## Secrets

- Live in Windows Credential Manager via the `keyring` library.
- `.env` is for non-secret development defaults only (it's gitignored regardless).
- OAuth refresh tokens stored in keyring, encrypted-at-rest by the OS.
- API keys are never logged, never echoed in audit rows (only a hash prefix for traceability).

## Audit log

- Append-only Postgres table; no UPDATE or DELETE permitted (enforced by a DB role).
- Every row: `timestamp, agent, domain, action_class, action_name, target_summary, input_hash, output_hash, decision, user_id, integration, latency_ms`.
- Audit log is queryable from the UI ("show me what Jarvis did yesterday").
- Sensitive payloads are not stored — only hashes — so the audit log itself isn't a leak vector.

## Sensitive-data handling

- Detector runs on inbound text (emails, OCR'd docs, user input) and flags: SSNs, credit cards, PHI patterns, API key shapes.
- Flagged content is never sent to cloud LLMs. The router falls back to local models or refuses.
- The Email Assistant's scam/phishing detector runs locally and is separate from the LLM (rules + small classifier).

## Computer Control safety

- App allow-list lives in DB; adding an app requires `admin` + typed confirmation.
- Script allow-list: scripts must be in `scripts/approved/` and pass a hash check on each run.
- `shell=True`, `subprocess.Popen` with user-supplied strings, and any path containing `..` are blocked at the integration layer, not just at the agent layer.

### Browser sessions (Playwright, Phase 9)

- Each session uses a **dedicated `user_data_dir`** under `JARVIS_BROWSER_PROFILES` (or a temp dir per process). Never the default Chrome profile.
- Profile directory is **wiped on session stop** by default — cookies don't leak across sessions.
- **Domain allow-list enforced at the integration layer** (`is_domain_allowed`): admin-only `BrowserAllowedDomain` rows declare which hosts the browser may navigate to. `localhost`/`127.0.0.1` always allowed.
- **Danger-word detection** on element text — `submit`, `send`, `buy`, `pay`, `order`, `charge`, `donate`, `confirm`, `delete`, `remove`, `unsubscribe`, `transfer`, `withdraw`, `deposit`, `invest`, `trade`, `sign up`, `agree`, `accept`, `continue to payment`, `checkout`, `complete`. A click on a matching element raises `DangerActionRequiresApproval` at the primitive layer; the agent then routes through `BaseAgent.propose` with `action.action_external_send`.
- `type_text(submit=True)` is refused at the primitive layer. Submitting a form requires the dedicated `submit` path which always queues an approval.
- **Idle timeout** (`idle_timeout_seconds`, default 600). The janitor (`reap_idle_sessions`) closes any session not touched within the window — prevents abandoned logged-in tabs.
- Every navigate / screenshot / click / type / submit attempt writes both a `BrowserAction` row (for debugging) and an `audit_log` row (for security).
- Lookalike-domain attacks (`github.com.evil.tld`) are rejected by fnmatch hostname matching — substring matches never count.

## Backups

- Nightly encrypted backup of the Postgres DB to a configurable local path (default: external drive).
- Backups encrypted with a key stored in keyring, separate from the auth key.
- Restore flow requires re-entering the master password.

## Threat model (brief)

| Threat | Mitigation |
|---|---|
| LLM convinced by a prompt-injected email to send money | Action class `external_send`/`financial` always require approval; LLM cannot escalate its own permission level |
| Malicious script in `scripts/approved/` | Hash check on each run; allow-list edits require `admin` + audit reason |
| Credential theft via local malware | Secrets in keyring (OS-protected); refresh tokens not in plaintext on disk; audit log surfaces unexpected API calls |
| Cross-client data leak | Domain tagging enforced at memory query layer; cross-domain reads logged |
| Cloud LLM exfiltrating sensitive content | Router refuses sensitive payloads for cloud calls; redaction pre-check |

## What this model deliberately does NOT promise

- Protection against an attacker with full local admin on this Windows machine. If they own the box, they own the keyring.
- Protection against you yourself approving a malicious action (e.g., a phishing email's drafted reply that you click "send" on without reading). The system surfaces, you decide.
- Quantum-resistant cryptography or anything beyond standard OS-level protections.
