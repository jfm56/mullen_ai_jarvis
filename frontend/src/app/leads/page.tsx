"use client";

/**
 * Lead Pipeline (Frontend v2).
 *
 * Surfaces the lead_generation backend end-to-end:
 *   - list + filter (status / vertical / min-score / open-only)
 *   - create (auto-scored server-side) + inline edit (re-scored on save)
 *   - recompute heuristic score on demand
 *   - recommended next-touch date, one-click apply
 *   - AI-drafted outreach that ROUTES THROUGH THE APPROVAL GATE — the draft is
 *     saved but the send is queued as a pending approval, settled on /approvals
 *   - per-lead outreach history
 *
 * Styling follows the established CRUD-page pattern (.card / .input / .pill /
 * .btn-*) on the HUD dark theme, using hud-* text tokens.
 */

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import {
  api,
  type DraftOutreachResult,
  type FollowupRecommendation,
  type Lead,
  type LeadInput,
  type LeadSource,
  type LeadStatus,
  type Outreach,
  type OutreachChannel,
  type Vertical,
} from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import {
  errText,
  fmtDate,
  fromLocalInput,
  isPast,
  titleCase,
  toLocalInput,
} from "@/lib/format";

const STATUSES: LeadStatus[] = [
  "researched",
  "contacted",
  "meeting",
  "proposal",
  "won",
  "lost",
  "disqualified",
];
const SOURCES: LeadSource[] = [
  "manual",
  "inbound_email",
  "referral",
  "event",
  "research",
  "other",
];
const VERTICALS: Vertical[] = [
  "healthcare",
  "ems",
  "fire",
  "drone",
  "ai_consulting",
  "school",
  "other",
];
const CHANNELS: OutreachChannel[] = ["email", "linkedin", "phone", "sms", "other"];

const VERTICAL_LABEL: Record<Vertical, string> = {
  healthcare: "Healthcare",
  ems: "EMS",
  fire: "Fire",
  drone: "Drone",
  ai_consulting: "AI Consulting",
  school: "School",
  other: "Other",
};

// ---- lead-specific display helpers --------------------------------------
function scoreColor(score: number): string {
  if (score >= 70) return "text-hud-accent";
  if (score >= 40) return "text-hud-text";
  return "text-hud-text_dim";
}

function statusPillClass(status: LeadStatus): string {
  switch (status) {
    case "won":
      return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
    case "lost":
    case "disqualified":
      return "border-hud-warning/40 bg-hud-warning/10 text-hud-warning";
    case "meeting":
    case "proposal":
      return "border-hud-accent_dim bg-hud-accent/10 text-hud-accent";
    default:
      return "border-hud-border bg-hud-bg/50 text-hud-text_dim";
  }
}

// ===========================================================================
// Page
// ===========================================================================
export default function LeadsPage() {
  const user = useRequireAuth();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Filters
  const [fStatus, setFStatus] = useState<"" | LeadStatus>("");
  const [fVertical, setFVertical] = useState<"" | Vertical>("");
  const [fMinScore, setFMinScore] = useState(0);
  const [fOpenOnly, setFOpenOnly] = useState(true);

  // Create form
  const [cName, setCName] = useState("");
  const [cCompany, setCCompany] = useState("");
  const [cRole, setCRole] = useState("");
  const [cEmail, setCEmail] = useState("");
  const [cPhone, setCPhone] = useState("");
  const [cVertical, setCVertical] = useState<Vertical>("ai_consulting");
  const [cSource, setCSource] = useState<LeadSource>("manual");
  const [cNotes, setCNotes] = useState("");

  // Discover (web search)
  const [dVertical, setDVertical] = useState<Vertical>("ems");
  const [dRegion, setDRegion] = useState("");
  const [dNeed, setDNeed] = useState("");
  const [discovering, setDiscovering] = useState(false);
  const [discoverNote, setDiscoverNote] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.listLeads({
        status: fStatus || undefined,
        vertical: fVertical || undefined,
        open_only: fOpenOnly,
        min_score: fMinScore || undefined,
      });
      setLeads(list);
      setError(null);
    } catch (err) {
      setError(errText(err, "could not load leads"));
    } finally {
      setLoading(false);
    }
  }, [fStatus, fVertical, fMinScore, fOpenOnly]);

  useEffect(() => {
    if (user) refresh();
  }, [user, refresh]);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!cName.trim() && !cCompany.trim() && !cEmail.trim()) {
      setError("give the lead at least a name, company, or email");
      return;
    }
    try {
      await api.createLead({
        name: cName.trim(),
        company: cCompany.trim(),
        role: cRole.trim(),
        email: cEmail.trim(),
        phone: cPhone.trim(),
        vertical: cVertical,
        source: cSource,
        notes: cNotes.trim(),
      });
      setCName("");
      setCCompany("");
      setCRole("");
      setCEmail("");
      setCPhone("");
      setCNotes("");
      setCVertical("ai_consulting");
      setCSource("manual");
      await refresh();
    } catch (err) {
      setError(errText(err, "create failed"));
    }
  }

  async function onDiscover(e: FormEvent) {
    e.preventDefault();
    setDiscovering(true);
    setDiscoverNote(null);
    setError(null);
    try {
      const res = await api.discoverLeads({
        vertical: dVertical,
        region: dRegion.trim(),
        need: dNeed.trim(),
      });
      setDiscoverNote(res.note);
      await refresh();
    } catch (err) {
      setError(errText(err, "discovery failed"));
    } finally {
      setDiscovering(false);
    }
  }

  if (!user) return null;

  const highScore = leads.filter((l) => l.score >= 70).length;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="hud-heading text-xl font-semibold text-hud-accent">
            Lead Pipeline
          </h1>
          <p className="mt-1 text-xs text-hud-text_dim">
            {leads.length} lead{leads.length === 1 ? "" : "s"} shown · {highScore}{" "}
            high-fit (≥70)
          </p>
        </div>
        <Link
          href="/approvals"
          className="text-xs text-hud-text_dim underline-offset-2 hover:text-hud-accent hover:underline"
        >
          Pending sends → Approvals
        </Link>
      </header>

      {/* Discover — web search → candidate orgs */}
      <form onSubmit={onDiscover} className="card space-y-2 border-hud-accent_dim">
        <div className="flex items-center justify-between">
          <div className="label text-hud-accent">Discover leads · web search</div>
          <span className="text-[10px] uppercase tracking-wide text-hud-text_dim">
            finds prospective client orgs + need signals
          </span>
        </div>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-[150px_1fr_1fr_auto]">
          <select
            className="input"
            value={dVertical}
            onChange={(e) => setDVertical(e.target.value as Vertical)}
            aria-label="discovery vertical"
          >
            {VERTICALS.map((v) => (
              <option key={v} value={v}>
                {VERTICAL_LABEL[v]}
              </option>
            ))}
          </select>
          <input
            className="input"
            placeholder="Region — e.g. New Jersey, Philadelphia metro"
            value={dRegion}
            onChange={(e) => setDRegion(e.target.value)}
          />
          <input
            className="input"
            placeholder="What they need — e.g. QA/QI, data analytics, grant help"
            value={dNeed}
            onChange={(e) => setDNeed(e.target.value)}
          />
          <button
            type="submit"
            className="btn-primary whitespace-nowrap"
            disabled={discovering}
          >
            {discovering ? "Searching…" : "Discover"}
          </button>
        </div>
        <p className="text-xs text-hud-text_dim">
          Searches the web, extracts real candidate organizations, and adds them here as{" "}
          <span className="text-hud-text">researched</span> leads to qualify — it never contacts
          anyone.{discovering && " This can take ~30–60s."}
        </p>
        {discoverNote && (
          <div className="rounded-sm border border-hud-accent_dim bg-hud-bg/50 p-2 text-xs text-hud-text">
            {discoverNote}
          </div>
        )}
      </form>

      {/* Filters */}
      <div className="card flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="label">Status</span>
          <select
            className="input"
            value={fStatus}
            onChange={(e) => setFStatus(e.target.value as "" | LeadStatus)}
          >
            <option value="">{fOpenOnly ? "All open" : "All"}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {titleCase(s)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="label">Vertical</span>
          <select
            className="input"
            value={fVertical}
            onChange={(e) => setFVertical(e.target.value as "" | Vertical)}
          >
            <option value="">All</option>
            {VERTICALS.map((v) => (
              <option key={v} value={v}>
                {VERTICAL_LABEL[v]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex w-28 flex-col gap-1">
          <span className="label">Min score</span>
          <input
            type="number"
            min={0}
            max={100}
            className="input"
            value={fMinScore}
            onChange={(e) =>
              setFMinScore(Math.max(0, Math.min(100, Number(e.target.value) || 0)))
            }
          />
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm text-hud-text_dim">
          <input
            type="checkbox"
            checked={fOpenOnly}
            onChange={(e) => setFOpenOnly(e.target.checked)}
          />
          Open only
        </label>
      </div>

      {/* Create */}
      <form onSubmit={onCreate} className="card space-y-2">
        <div className="label">Add lead</div>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          <input
            className="input"
            placeholder="Name"
            value={cName}
            onChange={(e) => setCName(e.target.value)}
          />
          <input
            className="input"
            placeholder="Company"
            value={cCompany}
            onChange={(e) => setCCompany(e.target.value)}
          />
          <input
            className="input"
            placeholder="Role / title"
            value={cRole}
            onChange={(e) => setCRole(e.target.value)}
          />
          <input
            className="input"
            placeholder="Email"
            value={cEmail}
            onChange={(e) => setCEmail(e.target.value)}
          />
          <input
            className="input"
            placeholder="Phone"
            value={cPhone}
            onChange={(e) => setCPhone(e.target.value)}
          />
          <div className="grid grid-cols-2 gap-2">
            <select
              className="input"
              value={cVertical}
              onChange={(e) => setCVertical(e.target.value as Vertical)}
            >
              {VERTICALS.map((v) => (
                <option key={v} value={v}>
                  {VERTICAL_LABEL[v]}
                </option>
              ))}
            </select>
            <select
              className="input"
              value={cSource}
              onChange={(e) => setCSource(e.target.value as LeadSource)}
            >
              {SOURCES.map((s) => (
                <option key={s} value={s}>
                  {titleCase(s)}
                </option>
              ))}
            </select>
          </div>
        </div>
        <textarea
          className="input"
          rows={2}
          placeholder="Notes — context, signal, what they need. Feeds the fit score and outreach draft."
          value={cNotes}
          onChange={(e) => setCNotes(e.target.value)}
        />
        <div className="flex justify-end">
          <button type="submit" className="btn-primary">
            Add lead
          </button>
        </div>
      </form>

      {error && (
        <div className="card border-hud-warning/50 text-sm text-hud-warning">
          {error}
        </div>
      )}

      {/* List */}
      {loading ? (
        <div className="card text-sm text-hud-text_dim">Loading…</div>
      ) : leads.length === 0 ? (
        <div className="card text-sm text-hud-text_dim">
          No leads match these filters. Add one above to get started.
        </div>
      ) : (
        <div className="space-y-2">
          {leads.map((lead) => (
            <LeadRow key={lead.id} lead={lead} onChanged={refresh} />
          ))}
        </div>
      )}
    </div>
  );
}

// ===========================================================================
// LeadRow — collapsed summary + expandable editor / outreach / activity.
// ===========================================================================
function LeadRow({ lead, onChanged }: { lead: Lead; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  // Edit buffer
  const [edit, setEdit] = useState<LeadInput | null>(null);

  // Follow-up recommendation
  const [rec, setRec] = useState<FollowupRecommendation | null>(null);

  // Outreach composer
  const [channel, setChannel] = useState<OutreachChannel>("email");
  const [instructions, setInstructions] = useState("");
  const [draft, setDraft] = useState<DraftOutreachResult | null>(null);

  // Outreach history (loaded lazily on expand)
  const [history, setHistory] = useState<Outreach[] | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api.listOutreach(lead.id));
    } catch {
      setHistory([]);
    }
  }, [lead.id]);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && history === null) void loadHistory();
  }

  function startEdit() {
    setEdit({
      name: lead.name,
      company: lead.company,
      role: lead.role,
      email: lead.email,
      phone: lead.phone,
      vertical: lead.vertical,
      source: lead.source,
      status: lead.status,
      notes: lead.notes,
      last_contacted_at: lead.last_contacted_at,
      next_followup_at: lead.next_followup_at,
    });
  }

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setRowError(null);
    try {
      await fn();
    } catch (err) {
      setRowError(errText(err, `${label} failed`));
    } finally {
      setBusy(null);
    }
  }

  async function saveEdit() {
    if (!edit) return;
    await run("save", async () => {
      await api.updateLead(lead.id, edit);
      setEdit(null);
      onChanged();
    });
  }

  async function rescore() {
    await run("rescore", async () => {
      await api.rescoreLead(lead.id);
      onChanged();
    });
  }

  async function getRecommendation() {
    await run("followup", async () => {
      setRec(await api.recommendFollowup(lead.id));
    });
  }

  async function applyRecommendation() {
    if (!rec) return;
    await run("apply", async () => {
      await api.updateLead(lead.id, { next_followup_at: rec.next_followup_at });
      setRec(null);
      onChanged();
    });
  }

  async function generateOutreach() {
    await run("outreach", async () => {
      const result = await api.draftOutreach(lead.id, {
        channel,
        user_instructions: instructions.trim(),
      });
      setDraft(result);
      await loadHistory();
    });
  }

  async function remove() {
    if (!confirm(`Delete lead "${lead.name || lead.company || lead.email}"?`)) return;
    await run("delete", async () => {
      await api.deleteLead(lead.id);
      onChanged();
    });
  }

  const overdue = isPast(lead.next_followup_at) && lead.status !== "won";
  const identity = lead.name || lead.company || lead.email || "(unnamed lead)";
  const subline = [lead.company && lead.name ? lead.company : null, lead.role]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="card space-y-3">
      {/* Summary line */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={toggle}
          className="flex flex-1 items-center gap-3 text-left"
          aria-expanded={open}
        >
          <span
            className={"font-mono text-lg font-bold tabular-nums " + scoreColor(lead.score)}
            title="fit score 0–100"
          >
            {lead.score}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm text-hud-text">{identity}</span>
            {subline && (
              <span className="block truncate text-xs text-hud-text_dim">{subline}</span>
            )}
          </span>
        </button>

        <span className={"pill border " + statusPillClass(lead.status)}>
          {titleCase(lead.status)}
        </span>
        <span className="pill">{VERTICAL_LABEL[lead.vertical]}</span>
        <span
          className={
            "text-xs " + (overdue ? "text-hud-warning" : "text-hud-text_dim")
          }
          title="next follow-up"
        >
          ↻ {fmtDate(lead.next_followup_at)}
          {overdue && " · DUE"}
        </span>
      </div>

      {rowError && (
        <div className="text-xs text-hud-warning">{rowError}</div>
      )}

      {open && (
        <div className="space-y-4 border-t border-hud-border pt-3">
          {/* Quick actions */}
          <div className="flex flex-wrap gap-2">
            <button
              className="btn-secondary"
              onClick={startEdit}
              disabled={edit !== null}
            >
              Edit
            </button>
            <button className="btn-secondary" onClick={rescore} disabled={busy === "rescore"}>
              {busy === "rescore" ? "Scoring…" : "Re-score"}
            </button>
            <button
              className="btn-secondary"
              onClick={getRecommendation}
              disabled={busy === "followup"}
            >
              {busy === "followup" ? "…" : "Recommend follow-up"}
            </button>
            <button className="btn-danger ml-auto" onClick={remove}>
              Delete
            </button>
          </div>

          {/* Follow-up recommendation */}
          {rec && (
            <div className="rounded-sm border border-hud-border bg-hud-bg/40 p-3 text-sm">
              <div className="text-hud-text">
                Suggested next touch:{" "}
                <span className="text-hud-accent">{fmtDate(rec.next_followup_at)}</span>
              </div>
              <div className="mt-1 text-xs text-hud-text_dim">{rec.reason}</div>
              {rec.next_followup_at && (
                <button
                  className="btn-primary mt-2"
                  onClick={applyRecommendation}
                  disabled={busy === "apply"}
                >
                  {busy === "apply" ? "Applying…" : "Apply date"}
                </button>
              )}
            </div>
          )}

          {/* Edit form */}
          {edit && (
            <div className="space-y-2 rounded-sm border border-hud-accent_dim bg-hud-bg/40 p-3">
              <div className="label">Edit lead</div>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                <input
                  className="input"
                  placeholder="Name"
                  value={edit.name}
                  onChange={(e) => setEdit({ ...edit, name: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Company"
                  value={edit.company}
                  onChange={(e) => setEdit({ ...edit, company: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Role"
                  value={edit.role}
                  onChange={(e) => setEdit({ ...edit, role: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Email"
                  value={edit.email}
                  onChange={(e) => setEdit({ ...edit, email: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Phone"
                  value={edit.phone}
                  onChange={(e) => setEdit({ ...edit, phone: e.target.value })}
                />
                <select
                  className="input"
                  value={edit.status}
                  onChange={(e) =>
                    setEdit({ ...edit, status: e.target.value as LeadStatus })
                  }
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {titleCase(s)}
                    </option>
                  ))}
                </select>
                <select
                  className="input"
                  value={edit.vertical}
                  onChange={(e) =>
                    setEdit({ ...edit, vertical: e.target.value as Vertical })
                  }
                >
                  {VERTICALS.map((v) => (
                    <option key={v} value={v}>
                      {VERTICAL_LABEL[v]}
                    </option>
                  ))}
                </select>
                <select
                  className="input"
                  value={edit.source}
                  onChange={(e) =>
                    setEdit({ ...edit, source: e.target.value as LeadSource })
                  }
                >
                  {SOURCES.map((s) => (
                    <option key={s} value={s}>
                      {titleCase(s)}
                    </option>
                  ))}
                </select>
                <label className="flex flex-col gap-1 text-xs text-hud-text_dim">
                  Last contacted
                  <input
                    type="datetime-local"
                    className="input"
                    value={toLocalInput(edit.last_contacted_at)}
                    onChange={(e) =>
                      setEdit({
                        ...edit,
                        last_contacted_at: fromLocalInput(e.target.value),
                      })
                    }
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs text-hud-text_dim">
                  Next follow-up
                  <input
                    type="datetime-local"
                    className="input"
                    value={toLocalInput(edit.next_followup_at)}
                    onChange={(e) =>
                      setEdit({
                        ...edit,
                        next_followup_at: fromLocalInput(e.target.value),
                      })
                    }
                  />
                </label>
              </div>
              <textarea
                className="input"
                rows={3}
                placeholder="Notes"
                value={edit.notes}
                onChange={(e) => setEdit({ ...edit, notes: e.target.value })}
              />
              <div className="flex gap-2">
                <button
                  className="btn-primary"
                  onClick={saveEdit}
                  disabled={busy === "save"}
                >
                  {busy === "save" ? "Saving…" : "Save (re-scores)"}
                </button>
                <button className="btn-secondary" onClick={() => setEdit(null)}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Notes (read-only when not editing) */}
          {!edit && lead.notes && (
            <p className="whitespace-pre-wrap text-sm text-hud-text_dim">{lead.notes}</p>
          )}

          {/* Outreach composer */}
          <div className="space-y-2 rounded-sm border border-hud-border bg-hud-bg/40 p-3">
            <div className="label">Draft outreach</div>
            <p className="text-xs text-hud-text_dim">
              Generates a message and <span className="text-hud-text">queues the send as a
              pending approval</span> — nothing is sent until you settle it on{" "}
              <Link href="/approvals" className="text-hud-accent hover:underline">
                Approvals
              </Link>
              .
            </p>
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1">
                <span className="label">Channel</span>
                <select
                  className="input"
                  value={channel}
                  onChange={(e) => setChannel(e.target.value as OutreachChannel)}
                >
                  {CHANNELS.map((c) => (
                    <option key={c} value={c}>
                      {titleCase(c)}
                    </option>
                  ))}
                </select>
              </label>
              <input
                className="input flex-1"
                placeholder="Optional steer — e.g. 'mention the AFG deadline, keep it under 100 words'"
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
              />
              <button
                className="btn-primary"
                onClick={generateOutreach}
                disabled={busy === "outreach"}
              >
                {busy === "outreach" ? "Drafting…" : "Generate"}
              </button>
            </div>

            {draft && (
              <div className="space-y-1 rounded-sm border border-hud-accent_dim bg-hud-bg/60 p-3">
                {draft.outreach.subject && (
                  <div className="text-sm font-semibold text-hud-text">
                    {draft.outreach.subject}
                  </div>
                )}
                <div className="whitespace-pre-wrap text-sm text-hud-text">
                  {draft.outreach.body_text}
                </div>
                <div className="mt-2 text-xs text-hud-text_dim">
                  {draft.approval_id ? (
                    <>
                      Send queued — approval{" "}
                      <Link href="/approvals" className="text-hud-accent hover:underline">
                        {draft.approval_id.slice(0, 8)}
                      </Link>{" "}
                      ({draft.approval_decision}). Not sent yet.
                    </>
                  ) : (
                    <>Draft saved ({draft.approval_decision}).</>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Outreach history */}
          {history && history.length > 0 && (
            <div className="space-y-1">
              <div className="label">Outreach history</div>
              <ul className="divide-y divide-hud-border">
                {history.map((m) => (
                  <li key={m.id} className="flex items-center justify-between gap-3 py-2 text-xs">
                    <span className="truncate text-hud-text">
                      {titleCase(m.channel)}
                      {m.subject ? ` · ${m.subject}` : ""}
                    </span>
                    <span className="shrink-0 text-hud-text_dim">
                      {m.status} · {fmtDate(m.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
