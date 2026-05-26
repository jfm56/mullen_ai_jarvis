"use client";

import { type FormEvent, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";

const AGENTS: { value: string; label: string; defaultDomain: string }[] = [
  { value: "personal_assistant", label: "Personal Assistant", defaultDomain: "personal" },
  { value: "email_assistant", label: "Email Assistant", defaultDomain: "personal" },
  { value: "project_manager", label: "Project Manager", defaultDomain: "business" },
  { value: "business_development", label: "Business Development", defaultDomain: "business" },
  { value: "grant_writer", label: "Grant Writer", defaultDomain: "business" },
  { value: "marketing", label: "Marketing", defaultDomain: "business" },
  { value: "lead_generation", label: "Lead Generation", defaultDomain: "business" },
  { value: "computer_control", label: "Computer Control", defaultDomain: "personal" },
];

const PERMISSION_LEVELS = [
  "read_only",
  "draft_only",
  "ask_before_action",
  "approved_automation",
  "admin",
];

interface Turn {
  id: number;
  agent: string;
  input: string;
  output: string | null;
  error: string | null;
  loading: boolean;
  metadata: Record<string, unknown> | null;
}

let turnCounter = 0;

export default function AgentsPage() {
  const user = useRequireAuth();
  const [agent, setAgent] = useState(AGENTS[0].value);
  const [domain, setDomain] = useState(AGENTS[0].defaultDomain);
  const [permission, setPermission] = useState("ask_before_action");
  const [prompt, setPrompt] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);

  function onAgentChange(value: string) {
    setAgent(value);
    const spec = AGENTS.find((a) => a.value === value);
    if (spec) setDomain(spec.defaultDomain);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!prompt.trim()) return;
    const turn: Turn = {
      id: ++turnCounter,
      agent,
      input: prompt,
      output: null,
      error: null,
      loading: true,
      metadata: null,
    };
    setTurns((prev) => [turn, ...prev]);
    setPrompt("");
    try {
      const result = await api.invokeAgent(agent, turn.input, domain, permission);
      setTurns((prev) =>
        prev.map((t) =>
          t.id === turn.id
            ? { ...t, output: result.text, metadata: result.metadata, loading: false }
            : t,
        ),
      );
    } catch (err) {
      setTurns((prev) =>
        prev.map((t) =>
          t.id === turn.id
            ? {
                ...t,
                error:
                  err instanceof ApiError && typeof err.detail === "string"
                    ? err.detail
                    : "agent call failed",
                loading: false,
              }
            : t,
        ),
      );
    }
  }

  if (!user) return null;

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <header>
        <h1 className="text-xl font-semibold text-brand-900">Agents</h1>
        <p className="text-sm text-brand-500">
          Pick an agent and ask it something. Drafts and actions still flow
          through Approvals.
        </p>
      </header>

      <form onSubmit={onSubmit} className="card space-y-3">
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          <div>
            <div className="label">Agent</div>
            <select
              className="input mt-1"
              value={agent}
              onChange={(e) => onAgentChange(e.target.value)}
            >
              {AGENTS.map((a) => (
                <option key={a.value} value={a.value}>{a.label}</option>
              ))}
            </select>
          </div>
          <div>
            <div className="label">Domain</div>
            <select
              className="input mt-1"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
            >
              <option value="personal">personal</option>
              <option value="business">business</option>
              <option value="public">public</option>
            </select>
          </div>
          <div>
            <div className="label">Permission level</div>
            <select
              className="input mt-1"
              value={permission}
              onChange={(e) => setPermission(e.target.value)}
            >
              {PERMISSION_LEVELS.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
        </div>
        <textarea
          className="input min-h-[100px] font-sans"
          placeholder="Ask the agent something."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
        <div className="flex justify-end">
          <button type="submit" className="btn-primary" disabled={!prompt.trim()}>
            Send
          </button>
        </div>
      </form>

      <div className="space-y-3">
        {turns.map((t) => (
          <div key={t.id} className="card">
            <div className="flex items-center justify-between">
              <span className="pill bg-brand-100 text-brand-700">{t.agent}</span>
              <span className="text-xs text-brand-500">
                {t.loading ? "thinking…" : t.error ? "error" : "done"}
              </span>
            </div>
            <div className="mt-2 rounded-md border border-brand-100 bg-brand-50 p-3">
              <div className="label">You</div>
              <pre className="mt-1 whitespace-pre-wrap text-sm text-brand-900">{t.input}</pre>
            </div>
            {t.error && (
              <div className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {t.error}
              </div>
            )}
            {t.output && (
              <div className="mt-2 rounded-md border border-brand-100 bg-white p-3">
                <div className="label">Agent</div>
                <pre className="mt-1 whitespace-pre-wrap text-sm text-brand-900">{t.output}</pre>
                {t.metadata && Object.keys(t.metadata).length > 0 && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-brand-500">
                      metadata
                    </summary>
                    <pre className="mt-1 whitespace-pre-wrap text-xs text-brand-500">
                      {JSON.stringify(t.metadata, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
