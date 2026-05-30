"use client";

/**
 * JARVIS command center root page.
 *
 * Composes the HUD components into the 12-col grid the design spec calls
 * for. CommandCenterShell already provides:
 *   - the fixed radial-gradient + hex-grid background
 *   - the sticky StatusStrip
 *   - column wrappers that scroll independently
 *
 * This page is responsible for fetching the data, deriving the metrics,
 * and slotting components into the left / center / right / reactor slots.
 *
 * Each fetch is wrapped in its own try/catch so a single failing endpoint
 * (e.g. /emails returning 404 on a fresh install) doesn't blank the page —
 * we show the spec's text_dim "—" placeholder instead.
 *
 * NOTE: the FloatingAssistant is already mounted in the root layout, so
 * we do NOT render it again here.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";

import { ApiError, api, request, type Project, type Task } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { VoiceButton } from "@/components/voice-button";
import { ArcReactor } from "@/components/hud/arc-reactor";
import { AgentRoster, type RosterAgent } from "@/components/hud/agent-roster";
import { CommandCenterShell } from "@/components/hud/command-center-shell";
import { HudPanel } from "@/components/hud/hud-panel";
import { ProjectProgress } from "@/components/hud/project-progress";
import { StatTile } from "@/components/hud/stat-tile";

// ---- Spec palette (mirrors the values in command-center-shell.tsx) ------
const PALETTE = {
  accent: "#22D3EE",
  text: "#F1F7FB",
  textDim: "#7A8FA6",
  border: "#15243B",
  warning: "#F5A524",
  glow: "rgba(34, 211, 238, 0.35)",
} as const;

// ---- Light view types for endpoints not in lib/api ---------------------
interface CalendarEventLite {
  id?: string;
  summary?: string;
  start?: string;
}

interface EmailLite {
  id?: string;
  subject?: string;
  is_read?: boolean;
}

interface AuditEntry {
  id: string;
  created_at: string;
  actor: string;
  action: string;
  detail?: string;
}

// ---- Greeting helper ---------------------------------------------------
function greetingForHour(hour: number): "morning" | "afternoon" | "evening" {
  if (hour < 12) return "morning";
  if (hour < 18) return "afternoon";
  return "evening";
}

// ---- Component ---------------------------------------------------------
export default function CommandCenterPage() {
  const user = useRequireAuth();

  // Greeting — recompute when the hour rolls over.
  const [greeting, setGreeting] = useState<"morning" | "afternoon" | "evening">(
    () => greetingForHour(new Date().getHours()),
  );
  useEffect(() => {
    const id = window.setInterval(
      () => setGreeting(greetingForHour(new Date().getHours())),
      60_000,
    );
    return () => window.clearInterval(id);
  }, []);

  // ---- Stat sources ----------------------------------------------------
  const [meetingsToday, setMeetingsToday] = useState<number | null>(null);
  const [openTasksCount, setOpenTasksCount] = useState<number | null>(null);
  const [pendingApprovals, setPendingApprovals] = useState<number | null>(null);
  const [unreadEmails, setUnreadEmails] = useState<number | null>(null);

  // Center column / right column data.
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [topTasks, setTopTasks] = useState<Task[] | null>(null);

  // Recent audit log (may not be available — endpoint is best-effort).
  const [audit, setAudit] = useState<AuditEntry[] | null>(null);
  const [auditAvailable, setAuditAvailable] = useState(true);

  // Ask Jarvis box.
  const [prompt, setPrompt] = useState("");
  const [paText, setPaText] = useState<string | null>(null);
  const [paLoading, setPaLoading] = useState(false);
  const [paError, setPaError] = useState<string | null>(null);

  // ---- Per-endpoint fetches, each isolated ----------------------------
  useEffect(() => {
    if (!user) return;
    let cancelled = false;

    // Calendar events for today (days_back=0, days_forward=1).
    (async () => {
      try {
        const events = await request<CalendarEventLite[]>("/calendar/events", {
          query: { days_back: 0, days_forward: 1 },
        });
        if (!cancelled) setMeetingsToday(Array.isArray(events) ? events.length : 0);
      } catch {
        if (!cancelled) setMeetingsToday(null);
      }
    })();

    // Open tasks (status=pending). Also use the same fetch to populate the
    // top-3 priorities list in the center column.
    (async () => {
      try {
        const tasks = await request<Task[]>("/tasks", {
          query: { status: "pending" },
        });
        if (cancelled) return;
        const list = Array.isArray(tasks) ? tasks : [];
        setOpenTasksCount(list.length);
        // Highest-priority first, then earliest due date.
        const rank: Record<string, number> = {
          urgent: 0,
          high: 1,
          normal: 2,
          low: 3,
        };
        const sorted = [...list].sort((a, b) => {
          const pa = rank[a.priority] ?? 99;
          const pb = rank[b.priority] ?? 99;
          if (pa !== pb) return pa - pb;
          const da = a.due_at ? new Date(a.due_at).getTime() : Infinity;
          const db = b.due_at ? new Date(b.due_at).getTime() : Infinity;
          return da - db;
        });
        setTopTasks(sorted.slice(0, 3));
      } catch {
        if (!cancelled) {
          setOpenTasksCount(null);
          setTopTasks(null);
        }
      }
    })();

    // Pending approvals.
    (async () => {
      try {
        const approvals = await request<unknown[]>("/approvals", {
          query: { status: "pending" },
        });
        if (!cancelled) {
          setPendingApprovals(Array.isArray(approvals) ? approvals.length : 0);
        }
      } catch {
        if (!cancelled) setPendingApprovals(null);
      }
    })();

    // Unread emails over last 7d. May 404 if the emails table is empty or
    // OAuth isn't connected yet — silently fall back to 0.
    (async () => {
      try {
        const emails = await request<EmailLite[]>("/emails", {
          query: { unread_only: true, days: 7 },
        });
        if (!cancelled) setUnreadEmails(Array.isArray(emails) ? emails.length : 0);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setUnreadEmails(0);
        } else {
          setUnreadEmails(null);
        }
      }
    })();

    // Active projects.
    (async () => {
      try {
        const all = await api.listProjects();
        if (!cancelled) {
          const active = (all ?? []).filter(
            (p) => (p.status ?? "").toLowerCase() === "active",
          );
          setProjects(active);
        }
      } catch {
        if (!cancelled) setProjects(null);
      }
    })();

    // Audit log — last 5 entries. Hide the panel if endpoint doesn't exist.
    (async () => {
      try {
        const entries = await request<AuditEntry[]>("/audit", {
          query: { limit: 5 },
        });
        if (!cancelled) {
          setAudit(Array.isArray(entries) ? entries : []);
          setAuditAvailable(true);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setAuditAvailable(false);
          setAudit(null);
        } else {
          // For any other error (e.g. 500) we still hide rather than spam.
          setAuditAvailable(false);
          setAudit(null);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [user]);

  // ---- Ask Jarvis submission -----------------------------------------
  const askJarvis = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setPaLoading(true);
    setPaError(null);
    setPaText(null);
    try {
      const resp = await api.invokeAgent("personal_assistant", trimmed, "personal");
      setPaText(resp.text ?? "");
    } catch (err) {
      setPaError(
        err instanceof ApiError && typeof err.detail === "string"
          ? err.detail
          : err instanceof Error
            ? err.message
            : "agent call failed",
      );
    } finally {
      setPaLoading(false);
    }
  }, []);

  const onSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      void askJarvis(prompt);
    },
    [askJarvis, prompt],
  );

  const onVoiceTranscript = useCallback(
    (text: string) => {
      setPrompt(text);
      void askJarvis(text);
    },
    [askJarvis],
  );

  // ---- Agent roster (static directory; live status would come from
  //      a /agents/status endpoint we haven't built yet). -------------
  const agents: RosterAgent[] = useMemo(
    () => [
      { id: "personal_assistant", name: "Personal Assistant", status: "idle" },
      { id: "email_assistant", name: "Email Assistant", status: "idle" },
      { id: "project_manager", name: "Project Manager", status: "idle" },
      { id: "business_development", name: "Business Dev", status: "idle" },
      { id: "marketing", name: "Marketing", status: "idle" },
      { id: "lead_generation", name: "Lead Gen", status: "idle" },
      { id: "computer_control", name: "Computer Control", status: "idle" },
      { id: "grant_writer", name: "Grant Writer", status: "idle" },
    ],
    [],
  );

  // ---- Render guards (must stay AFTER all hooks above) --------------
  if (!user) return null;

  // ---- Derived view values -----------------------------------------
  const dash = (
    <span style={{ color: PALETTE.textDim, fontFamily: "JetBrains Mono, monospace" }}>
      —
    </span>
  );

  // Project progress derivation — backend Project model doesn't expose
  // completed_tasks / total_tasks yet, so we look for them defensively
  // and fall back to 0%. Once the backend ships those fields, this
  // line will start showing real progress with no further changes.
  function projectPercent(p: Project): number {
    const anyP = p as unknown as { completed_tasks?: number; total_tasks?: number };
    const total = anyP.total_tasks ?? 0;
    const done = anyP.completed_tasks ?? 0;
    if (!total || total <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
  }

  // ---- Slot: left column (stat tiles) ------------------------------
  const leftSlot = (
    <>
      <StatTile label="Meetings Today" value={meetingsToday ?? 0} />
      <StatTile
        label="Open Tasks"
        value={openTasksCount ?? 0}
        tone={openTasksCount && openTasksCount > 10 ? "warning" : "default"}
      />
      <StatTile
        label="Pending Approvals"
        value={pendingApprovals ?? 0}
        tone={pendingApprovals && pendingApprovals > 0 ? "warning" : "default"}
      />
      <StatTile label="Unread Emails" value={unreadEmails ?? 0} />
    </>
  );

  // ---- Slot: right column (active initiatives + recent activity) --
  const rightSlot = (
    <>
      <HudPanel label="ACTIVE INITIATIVES" tone="default">
        {projects === null ? (
          <div style={{ color: PALETTE.textDim, fontSize: "12px" }}>
            unable to load projects
          </div>
        ) : projects.length === 0 ? (
          <div style={{ color: PALETTE.textDim, fontSize: "12px" }}>
            No active projects.
          </div>
        ) : (
          projects.slice(0, 5).map((p) => (
            <ProjectProgress
              key={p.id}
              name={p.name}
              percent={projectPercent(p)}
              deadline={p.target_end_date ?? undefined}
              subline={p.client || undefined}
            />
          ))
        )}
      </HudPanel>

      {auditAvailable && audit !== null ? (
        <HudPanel label="RECENT ACTIVITY" tone="default">
          {audit.length === 0 ? (
            <div style={{ color: PALETTE.textDim, fontSize: "12px" }}>
              Nothing recent.
            </div>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {audit.map((entry) => (
                <li
                  key={entry.id}
                  style={{
                    padding: "6px 0",
                    borderBottom: `1px solid ${PALETTE.border}`,
                    fontFamily: "Exo 2, sans-serif",
                    fontSize: "12px",
                    color: PALETTE.text,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "8px" }}>
                    <span style={{ fontWeight: 500 }}>{entry.action}</span>
                    <span
                      style={{
                        color: PALETTE.textDim,
                        fontFamily: "JetBrains Mono, monospace",
                        fontSize: "10px",
                      }}
                    >
                      {new Date(entry.created_at).toLocaleTimeString(undefined, {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                  {entry.detail ? (
                    <div style={{ color: PALETTE.textDim, marginTop: "2px" }}>
                      {entry.detail}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </HudPanel>
      ) : null}
    </>
  );

  // ---- Slot: reactor (with greeting underneath) -------------------
  const reactorState: "idle" | "listening" | "thinking" = paLoading
    ? "thinking"
    : "idle";

  const greetingStyle: CSSProperties = {
    fontFamily: "Orbitron, sans-serif",
    fontSize: "15px",
    letterSpacing: "0.18em",
    textTransform: "uppercase",
    color: PALETTE.accent,
    textShadow: `0 0 10px ${PALETTE.glow}`,
    marginTop: "16px",
    textAlign: "center",
  };
  const subGreetingStyle: CSSProperties = {
    fontFamily: "Exo 2, sans-serif",
    fontSize: "12px",
    color: PALETTE.textDim,
    marginTop: "4px",
    textAlign: "center",
    letterSpacing: "0.05em",
  };

  const reactorSlot = (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <ArcReactor size={280} state={reactorState} />
      <div style={greetingStyle}>
        Good {greeting}, {user.display_name}
      </div>
      <div style={subGreetingStyle}>
        {new Date().toLocaleDateString(undefined, {
          weekday: "long",
          month: "long",
          day: "numeric",
          year: "numeric",
        })}
      </div>
    </div>
  );

  // ---- Center column children: priorities, agent roster, ask jarvis ----
  const priorityListStyle: CSSProperties = {
    listStyle: "none",
    counterReset: "priority",
    margin: 0,
    padding: 0,
  };
  const priorityItemStyle: CSSProperties = {
    fontFamily: "Exo 2, sans-serif",
    fontSize: "14px",
    color: PALETTE.text,
    padding: "8px 0",
    borderBottom: `1px solid ${PALETTE.border}`,
    display: "flex",
    gap: "12px",
  };
  const priorityNumStyle: CSSProperties = {
    fontFamily: "Orbitron, sans-serif",
    fontSize: "16px",
    color: PALETTE.accent,
    fontWeight: 700,
    minWidth: "20px",
  };

  return (
    <CommandCenterShell
      statusLabel={`JARVIS // ${user.display_name.toUpperCase()}`}
      left={leftSlot}
      right={rightSlot}
      reactor={reactorSlot}
    >
      {/* Today's top three priorities */}
      <HudPanel label="TOP PRIORITIES" tone="default">
        {topTasks === null ? (
          <div style={{ color: PALETTE.textDim, fontSize: "12px" }}>
            unable to load tasks
          </div>
        ) : topTasks.length === 0 ? (
          <div style={{ color: PALETTE.textDim, fontSize: "13px" }}>
            All clear. Nothing pending. {dash}
          </div>
        ) : (
          <ol style={priorityListStyle}>
            {topTasks.map((t, i) => (
              <li key={t.id} style={priorityItemStyle}>
                <span style={priorityNumStyle}>{i + 1}.</span>
                <span style={{ flex: 1 }}>
                  <span>{t.title}</span>
                  {t.due_at ? (
                    <span
                      style={{
                        display: "block",
                        color: PALETTE.textDim,
                        fontSize: "11px",
                        marginTop: "2px",
                      }}
                    >
                      due {new Date(t.due_at).toLocaleString(undefined, {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  ) : null}
                </span>
                <span
                  style={{
                    fontFamily: "JetBrains Mono, monospace",
                    fontSize: "10px",
                    color:
                      t.priority === "urgent"
                        ? PALETTE.warning
                        : t.priority === "high"
                          ? PALETTE.accent
                          : PALETTE.textDim,
                    textTransform: "uppercase",
                    letterSpacing: "0.1em",
                  }}
                >
                  {t.priority}
                </span>
              </li>
            ))}
          </ol>
        )}
      </HudPanel>

      {/* Agent roster */}
      <HudPanel label="AGENT ROSTER" tone="default">
        <AgentRoster agents={agents} />
      </HudPanel>

      {/* Ask Jarvis composer */}
      <HudPanel label="ASK JARVIS" tone="accent">
        <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="What do you need? e.g. 'summarize today' or 'draft a reply to the EMS director'."
            rows={3}
            style={{
              backgroundColor: "rgba(5,8,15,0.6)",
              border: `1px solid ${PALETTE.border}`,
              color: PALETTE.text,
              padding: "10px",
              fontFamily: "Exo 2, sans-serif",
              fontSize: "13px",
              outline: "none",
              resize: "vertical",
              minHeight: "60px",
            }}
          />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <VoiceButton onTranscript={onVoiceTranscript} replyText={paText} />
            <button
              type="submit"
              disabled={paLoading || !prompt.trim()}
              style={{
                backgroundColor: paLoading ? "transparent" : "rgba(34,211,238,0.15)",
                border: `1px solid ${PALETTE.accent}`,
                color: PALETTE.accent,
                padding: "8px 18px",
                fontFamily: "Orbitron, sans-serif",
                fontSize: "11px",
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                cursor: paLoading || !prompt.trim() ? "not-allowed" : "pointer",
                opacity: paLoading || !prompt.trim() ? 0.5 : 1,
                boxShadow: paLoading ? "none" : `0 0 12px ${PALETTE.glow}`,
                transition: "opacity 150ms ease, box-shadow 150ms ease",
              }}
            >
              {paLoading ? "Thinking…" : "Send"}
            </button>
          </div>
          {paError ? (
            <div
              style={{
                border: `1px solid ${PALETTE.warning}`,
                color: PALETTE.warning,
                fontSize: "12px",
                padding: "6px 10px",
                fontFamily: "Exo 2, sans-serif",
              }}
            >
              {paError}
            </div>
          ) : null}
          {paText ? (
            <div
              style={{
                border: `1px solid ${PALETTE.border}`,
                background: "rgba(5,8,15,0.5)",
                color: PALETTE.text,
                padding: "10px",
                fontFamily: "Exo 2, sans-serif",
                fontSize: "13px",
                whiteSpace: "pre-wrap",
              }}
            >
              {paText}
            </div>
          ) : null}
        </form>
      </HudPanel>
    </CommandCenterShell>
  );
}
