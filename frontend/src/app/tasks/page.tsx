"use client";

import { type FormEvent, useEffect, useState } from "react";

import { ApiError, api, type Task } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";

const PRIORITIES = ["low", "normal", "high", "urgent"] as const;

export default function TasksPage() {
  const user = useRequireAuth();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState<typeof PRIORITIES[number]>("normal");
  const [dueAt, setDueAt] = useState("");

  async function refresh() {
    try {
      setTasks(await api.listTasks());
    } catch (err) {
      setError(
        err instanceof ApiError && typeof err.detail === "string"
          ? err.detail
          : "could not load tasks",
      );
    }
  }

  useEffect(() => {
    if (user) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    try {
      await api.createTask({
        title: title.trim(),
        priority,
        due_at: dueAt ? new Date(dueAt).toISOString() : null,
      });
      setTitle("");
      setPriority("normal");
      setDueAt("");
      await refresh();
    } catch (err) {
      setError(
        err instanceof ApiError && typeof err.detail === "string"
          ? err.detail
          : "create failed",
      );
    }
  }

  async function toggleDone(t: Task) {
    const next = t.status === "done" ? "pending" : "done";
    await api.updateTask(t.id, { status: next });
    await refresh();
  }

  async function onDelete(id: string) {
    if (!confirm("Delete this task?")) return;
    await api.deleteTask(id);
    await refresh();
  }

  if (!user) return null;

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <header>
        <h1 className="text-xl font-semibold text-brand-900">Tasks</h1>
      </header>

      <form onSubmit={onCreate} className="card space-y-2">
        <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_120px_180px_auto]">
          <input
            className="input"
            placeholder="What needs doing?"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <select
            className="input"
            value={priority}
            onChange={(e) => setPriority(e.target.value as typeof PRIORITIES[number])}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          <input
            type="datetime-local"
            className="input"
            value={dueAt}
            onChange={(e) => setDueAt(e.target.value)}
          />
          <button type="submit" className="btn-primary">Add</button>
        </div>
      </form>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="card">
        {tasks.length === 0 ? (
          <div className="text-sm text-brand-500">No tasks.</div>
        ) : (
          <ul className="divide-y divide-brand-100">
            {tasks.map((t) => {
              const overdue = t.due_at && new Date(t.due_at) < new Date() && t.status !== "done";
              return (
                <li key={t.id} className="flex items-center justify-between gap-3 py-2">
                  <label className="flex flex-1 items-center gap-3">
                    <input
                      type="checkbox"
                      checked={t.status === "done"}
                      onChange={() => toggleDone(t)}
                    />
                    <div>
                      <div
                        className={
                          "text-sm " +
                          (t.status === "done"
                            ? "text-brand-300 line-through"
                            : "text-brand-900")
                        }
                      >
                        {t.title}
                      </div>
                      {t.due_at && (
                        <div className={"text-xs " + (overdue ? "text-red-700" : "text-brand-500")}>
                          due {new Date(t.due_at).toLocaleString()}
                          {overdue && " · OVERDUE"}
                        </div>
                      )}
                    </div>
                  </label>
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
                  <button
                    onClick={() => onDelete(t.id)}
                    className="text-xs text-brand-500 hover:text-red-700"
                    aria-label={`Delete ${t.title}`}
                  >
                    delete
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
