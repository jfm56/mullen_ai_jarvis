"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, api, type Approval } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { ApprovalCard } from "@/components/approval-card";

export default function ApprovalsPage() {
  const user = useRequireAuth();
  const [approvals, setApprovals] = useState<Approval[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const rows = await api.listApprovals();
      setApprovals(rows);
    } catch (err) {
      setError(
        err instanceof ApiError && typeof err.detail === "string"
          ? err.detail
          : "could not load approvals",
      );
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    refresh();
  }, [user, refresh]);

  if (!user) return null;

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-brand-900">Pending approvals</h1>
          <p className="text-sm text-brand-500">
            Every externally-visible action waits here for your decision.
          </p>
        </div>
        <button onClick={refresh} className="btn-secondary">
          Refresh
        </button>
      </header>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {approvals === null && !error && (
        <div className="text-sm text-brand-500">Loading…</div>
      )}

      {approvals && approvals.length === 0 && (
        <div className="card text-sm text-brand-500">
          Nothing pending. The agents are waiting for you to give them work to do.
        </div>
      )}

      <div className="space-y-3">
        {approvals?.map((a) => (
          <ApprovalCard key={a.id} approval={a} onDecided={refresh} />
        ))}
      </div>
    </div>
  );
}
