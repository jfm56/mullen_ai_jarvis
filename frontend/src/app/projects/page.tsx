"use client";

import { useEffect, useState } from "react";

import { ApiError, api, type Project } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-100 text-green-800",
  proposal: "bg-amber-100 text-amber-800",
  paused: "bg-brand-100 text-brand-700",
  won: "bg-emerald-100 text-emerald-800",
  lost: "bg-brand-100 text-brand-500",
  archived: "bg-brand-50 text-brand-500",
};

export default function ProjectsPage() {
  const user = useRequireAuth();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    api
      .listProjects()
      .then(setProjects)
      .catch((err: unknown) => {
        setError(
          err instanceof ApiError && typeof err.detail === "string"
            ? err.detail
            : "could not load projects",
        );
      });
  }, [user]);

  if (!user) return null;

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <header>
        <h1 className="text-xl font-semibold text-brand-900">Projects</h1>
        <p className="text-sm text-brand-500">
          Active work across healthcare, EMS, fire, drone, AI consulting, school.
        </p>
      </header>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {projects === null && !error && (
        <div className="text-sm text-brand-500">Loading…</div>
      )}

      {projects && projects.length === 0 && (
        <div className="card text-sm text-brand-500">
          No projects yet. Create one with{" "}
          <code className="rounded bg-brand-50 px-1">POST /projects</code> or run a
          curl/script for now — full UI lands in a later iteration.
        </div>
      )}

      {projects && projects.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-brand-100 text-left text-xs uppercase tracking-wide text-brand-500">
                <th className="py-2 pr-3">Name</th>
                <th className="py-2 pr-3">Client</th>
                <th className="py-2 pr-3">Vertical</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Priority</th>
                <th className="py-2 pr-3">Target</th>
                <th className="py-2 pr-3">Value</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className="border-b border-brand-100 last:border-0">
                  <td className="py-2 pr-3 text-brand-900">{p.name}</td>
                  <td className="py-2 pr-3 text-brand-700">{p.client || "—"}</td>
                  <td className="py-2 pr-3 text-brand-700">{p.vertical}</td>
                  <td className="py-2 pr-3">
                    <span className={"pill " + (STATUS_COLORS[p.status] ?? "bg-brand-100 text-brand-700")}>
                      {p.status}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-brand-700">P{p.priority}</td>
                  <td className="py-2 pr-3 text-brand-700">
                    {p.target_end_date ? new Date(p.target_end_date).toLocaleDateString() : "—"}
                  </td>
                  <td className="py-2 pr-3 text-brand-700">
                    {p.value_estimate ? `$${p.value_estimate.toLocaleString()}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
