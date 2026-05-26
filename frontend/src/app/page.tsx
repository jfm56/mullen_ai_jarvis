"use client";

import { type FormEvent, useEffect, useState } from "react";

import { ApiError, api, type Task } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { VoiceButton } from "@/components/voice-button";

interface PaState {
  text: string | null;
  metadata: Record<string, unknown> | null;
  loading: boolean;
  error: string | null;
}

export default function TodayPage() {
  const user = useRequireAuth();
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [tasksError, setTasksError] = useState<string | null>(null);

  const [prompt, setPrompt] = useState("");
  const [pa, setPa] = useState<PaState>({
    text: null,
    metadata: null,
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    api
      .listTasks()
      .then((rows) => {
        if (!cancelled) setTasks(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setTasksError(
            err instanceof ApiError && typeof err.detail === "string"
              ? err.detail
              : "could not load tasks",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  async function invoke(promptText: string) {
    if (!promptText.trim()) return;
    setPa({ text: null, metadata: null, loading: true, error: null });
    try {
      const result = await api.invokeAgent("personal_assistant", promptText, "personal");
      setPa({
        text: result.text,
        metadata: result.metadata,
        loading: false,
        error: null,
      });
    } catch (err) {
      setPa({
        text: null,
        metadata: null,
        loading: false,
        error:
          err instanceof ApiError && typeof err.detail === "string"
            ? err.detail
            : "agent call failed",
      });
    }
  }

  async function askPersonalAssistant(e: FormEvent) {
    e.preventDefault();
    await invoke(prompt);
  }

  function onVoiceTranscript(text: string) {
    setPrompt(text);
    void invoke(text);
  }

  if (!user) return null;

  const openTasks = tasks?.filter((t) => t.status !== "done" && t.status !== "cancelled") ?? [];
  const overdueTasks = openTasks.filter(
    (t) => t.due_at && new Date(t.due_at) < new Date(),
  );

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-brand-900">
          Good to see you, {user.display_name}.
        </h1>
        <p className="text-sm text-brand-500">
          {new Date().toLocaleDateString(undefined, {
            weekday: "long",
            month: "long",
            day: "numeric",
            year: "numeric",
          })}
        </p>
      </header>

      <section className="card">
        <h2 className="text-sm font-semibold text-brand-900">Ask Jarvis</h2>
        <form onSubmit={askPersonalAssistant} className="mt-3 space-y-2">
          <textarea
            className="input min-h-[80px] font-sans"
            placeholder="e.g., what's on my plate today? or add a task to call the EMS director tomorrow."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <div className="flex items-center justify-between gap-2">
            <VoiceButton onTranscript={onVoiceTranscript} replyText={pa.text} />
            <button
              type="submit"
              className="btn-primary"
              disabled={pa.loading || !prompt.trim()}
            >
              {pa.loading ? "Thinking…" : "Send"}
            </button>
          </div>
        </form>
        {pa.error && (
          <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {pa.error}
          </div>
        )}
        {pa.text && (
          <div className="mt-3 rounded-md border border-brand-100 bg-brand-50 p-3">
            <pre className="whitespace-pre-wrap text-sm text-brand-900">{pa.text}</pre>
            {pa.metadata && (
              <div className="mt-2 text-xs text-brand-500">
                events: {String(pa.metadata.events ?? 0)} · open tasks:{" "}
                {String(pa.metadata.open_tasks ?? 0)} · overdue:{" "}
                {String(pa.metadata.overdue_tasks ?? 0)} · reminders:{" "}
                {String(pa.metadata.reminders ?? 0)}
              </div>
            )}
          </div>
        )}
      </section>

      <section className="card">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-brand-900">Open tasks</h2>
          <a href="/tasks" className="text-xs text-brand-700 underline">
            manage →
          </a>
        </div>
        {tasksError && (
          <div className="mt-2 text-xs text-red-700">{tasksError}</div>
        )}
        {tasks === null && !tasksError && (
          <div className="mt-2 text-xs text-brand-500">Loading…</div>
        )}
        {tasks && openTasks.length === 0 && (
          <div className="mt-2 text-sm text-brand-500">No open tasks. Nice.</div>
        )}
        {openTasks.length > 0 && (
          <ul className="mt-2 divide-y divide-brand-100">
            {openTasks.slice(0, 8).map((t) => {
              const overdue = t.due_at && new Date(t.due_at) < new Date();
              return (
                <li key={t.id} className="flex items-start justify-between py-2">
                  <div>
                    <div className="text-sm text-brand-900">{t.title}</div>
                    {t.due_at && (
                      <div
                        className={
                          "text-xs " + (overdue ? "text-red-700" : "text-brand-500")
                        }
                      >
                        due {new Date(t.due_at).toLocaleString()}
                        {overdue && " · OVERDUE"}
                      </div>
                    )}
                  </div>
                  <span
                    className={
                      "pill " +
                      (t.priority === "urgent"
                        ? "bg-red-100 text-red-800"
                        : t.priority === "high"
                          ? "bg-amber-100 text-amber-800"
                          : "bg-brand-100 text-brand-700")
                    }
                  >
                    {t.priority}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {overdueTasks.length > 0 && (
          <div className="mt-2 text-xs text-red-700">
            {overdueTasks.length} overdue
          </div>
        )}
      </section>
    </div>
  );
}
