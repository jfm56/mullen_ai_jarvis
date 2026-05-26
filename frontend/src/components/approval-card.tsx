"use client";

import { useState } from "react";

import { ApiError, api, type Approval } from "@/lib/api";

/**
 * One approval card. Surfaces the agent, action class, target summary,
 * preview, and a note field. For destructive Computer Control actions
 * the agent's payload includes `confirmation_phrase`; we show a callout
 * reminding the user to type the phrase into the note.
 */
export function ApprovalCard({
  approval,
  onDecided,
}: {
  approval: Approval;
  onDecided: () => void;
}) {
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const destructive =
    approval.action_class === "action.destructive" ||
    approval.action_class === "action.system" ||
    approval.action_class === "action.financial";

  const requiresTypedPhrase =
    typeof approval.payload?.confirmation_phrase === "string" &&
    (approval.payload.confirmation_phrase as string).length > 0;
  const requiredPhrase = requiresTypedPhrase
    ? (approval.payload.confirmation_phrase as string)
    : "";

  async function decide(approve: boolean) {
    setSubmitting(true);
    setError(null);
    try {
      await api.decideApproval(approval.id, approve, note);
      onDecided();
    } catch (err) {
      setError(
        err instanceof ApiError && typeof err.detail === "string"
          ? err.detail
          : "decision failed",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="pill bg-brand-100 text-brand-700">{approval.agent}</span>
            <span
              className={
                "pill " +
                (destructive
                  ? "bg-red-100 text-red-800"
                  : "bg-amber-100 text-amber-800")
              }
            >
              {approval.action_class}
            </span>
            <span className="text-xs text-brand-500">{approval.action_name}</span>
          </div>
          <div className="mt-1 text-sm font-medium text-brand-900">
            {approval.target_summary}
          </div>
        </div>
        <div className="text-right text-xs text-brand-500">
          {new Date(approval.created_at).toLocaleString()}
          {approval.expires_at && (
            <div>expires {new Date(approval.expires_at).toLocaleString()}</div>
          )}
        </div>
      </div>

      {approval.preview && (
        <div className="mt-3">
          <div className="label">Preview</div>
          <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md border border-brand-100 bg-brand-50 p-3 text-xs text-brand-900">
            {approval.preview}
          </pre>
        </div>
      )}

      {requiresTypedPhrase && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          This action is destructive. Type{" "}
          <code className="rounded bg-white px-1 font-mono">{requiredPhrase}</code>{" "}
          in the note below to confirm — clicking Approve alone is not enough.
        </div>
      )}

      <div className="mt-3">
        <div className="label">Note (optional)</div>
        <textarea
          className="input mt-1 min-h-[60px] font-sans"
          placeholder={
            requiresTypedPhrase
              ? `type "${requiredPhrase}" to confirm`
              : "why or why not (will be stored on the approval and propagated to memory)"
          }
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>

      {error && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={() => decide(false)}
          className="btn-secondary"
          disabled={submitting}
        >
          Reject
        </button>
        <button
          type="button"
          onClick={() => decide(true)}
          className={destructive ? "btn-danger" : "btn-primary"}
          disabled={
            submitting ||
            (requiresTypedPhrase && !note.includes(requiredPhrase))
          }
        >
          {submitting ? "Saving…" : "Approve"}
        </button>
      </div>
    </div>
  );
}
