"use client";

import { useEffect, useState } from "react";

import { ApiError, api, type Grant } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";

const STATUS_COLORS: Record<string, string> = {
  intake: "bg-brand-100 text-brand-700",
  eligibility: "bg-amber-100 text-amber-800",
  drafting: "bg-blue-100 text-blue-800",
  review: "bg-indigo-100 text-indigo-800",
  ready: "bg-emerald-100 text-emerald-800",
  submitted: "bg-purple-100 text-purple-800",
  awarded: "bg-green-100 text-green-800",
  declined: "bg-brand-100 text-brand-500",
  withdrawn: "bg-brand-50 text-brand-500",
};

const VERDICT_COLORS: Record<string, string> = {
  pass: "bg-green-100 text-green-800",
  fail: "bg-red-100 text-red-800",
  needs_review: "bg-amber-100 text-amber-800",
  pending: "bg-brand-100 text-brand-500",
  skipped: "bg-brand-50 text-brand-500",
};

export default function GrantsPage() {
  const user = useRequireAuth();
  const [grants, setGrants] = useState<Grant[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    api
      .listGrants()
      .then(setGrants)
      .catch((err: unknown) => {
        setError(
          err instanceof ApiError && typeof err.detail === "string"
            ? err.detail
            : "could not load grants",
        );
      });
  }, [user]);

  if (!user) return null;

  const now = Date.now();

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <header>
        <h1 className="text-xl font-semibold text-brand-900">Grants</h1>
        <p className="text-sm text-brand-500">
          Federal (NIH/SAMHSA/HRSA/FEMA AFG/DOJ), state, and foundation applications.
          Section drafting + bundle assembly UI lands in a later iteration; use the
          API directly for now.
        </p>
      </header>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {grants === null && !error && (
        <div className="text-sm text-brand-500">Loading…</div>
      )}

      {grants && grants.length === 0 && (
        <div className="card text-sm text-brand-500">
          No grants yet.
        </div>
      )}

      {grants && grants.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-brand-100 text-left text-xs uppercase tracking-wide text-brand-500">
                <th className="py-2 pr-3">Title</th>
                <th className="py-2 pr-3">Funder</th>
                <th className="py-2 pr-3">Mechanism</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Eligibility</th>
                <th className="py-2 pr-3">Requested</th>
                <th className="py-2 pr-3">Deadline</th>
              </tr>
            </thead>
            <tbody>
              {grants.map((g) => {
                const dl = g.deadline ? new Date(g.deadline) : null;
                const overdue = dl && dl.getTime() < now;
                return (
                  <tr key={g.id} className="border-b border-brand-100 last:border-0">
                    <td className="py-2 pr-3 text-brand-900">{g.title}</td>
                    <td className="py-2 pr-3 text-brand-700">
                      {g.funder_type}
                      {g.funder_name ? ` · ${g.funder_name}` : ""}
                    </td>
                    <td className="py-2 pr-3 text-brand-700">{g.mechanism_code || "—"}</td>
                    <td className="py-2 pr-3">
                      <span className={"pill " + (STATUS_COLORS[g.status] ?? "bg-brand-100 text-brand-700")}>
                        {g.status}
                      </span>
                    </td>
                    <td className="py-2 pr-3">
                      <span className={"pill " + (VERDICT_COLORS[g.eligibility_verdict] ?? "bg-brand-100 text-brand-700")}>
                        {g.eligibility_verdict}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-brand-700">
                      {g.requested_amount ? `$${g.requested_amount.toLocaleString()}` : "—"}
                    </td>
                    <td className={"py-2 pr-3 " + (overdue ? "text-red-700" : "text-brand-700")}>
                      {dl ? dl.toLocaleDateString() : "—"}
                      {overdue && " · overdue"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
