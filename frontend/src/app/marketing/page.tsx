"use client";

/**
 * Marketing content calendar (Frontend v2).
 *
 * Surfaces the marketing agent end-to-end:
 *   - filter posts by status / platform / vertical
 *   - suggest topics per vertical (seed list from the backend)
 *   - AI-draft a post for a platform+vertical+topic. The draft is saved as a
 *     `draft` post AND a publish approval is queued — NOTHING publishes until
 *     that approval is settled on /approvals.
 *   - inline-edit the copy, schedule it (status=scheduled + date), or discard
 *
 * Publishing is intentionally NOT a one-click action here: it goes through the
 * approval gate, honoring the system's "never auto-post" rule.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  api,
  type DraftPostResult,
  type SocialPlatform,
  type SocialPost,
  type SocialPostStatus,
  type Vertical,
} from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import {
  errText,
  fmtDate,
  fmtDateTime,
  titleCase,
  toLocalInput,
  fromLocalInput,
} from "@/lib/format";

const PLATFORMS: SocialPlatform[] = [
  "linkedin",
  "facebook",
  "x",
  "instagram",
  "blog",
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
// Statuses a user can set by hand. "published" is deliberately excluded —
// publishing happens by settling the post's approval, not by a dropdown.
const EDIT_STATUSES: SocialPostStatus[] = ["draft", "scheduled", "discarded"];

const PLATFORM_LABEL: Record<SocialPlatform, string> = {
  linkedin: "LinkedIn",
  facebook: "Facebook",
  x: "X",
  instagram: "Instagram",
  blog: "Blog",
  other: "Other",
};
const VERTICAL_LABEL: Record<Vertical, string> = {
  healthcare: "Healthcare",
  ems: "EMS",
  fire: "Fire",
  drone: "Drone",
  ai_consulting: "AI Consulting",
  school: "School",
  other: "Other",
};

function statusPillClass(s: SocialPostStatus): string {
  switch (s) {
    case "published":
      return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
    case "scheduled":
      return "border-hud-accent_dim bg-hud-accent/10 text-hud-accent";
    case "discarded":
      return "border-hud-warning/40 bg-hud-warning/10 text-hud-warning";
    default:
      return "border-hud-border bg-hud-bg/50 text-hud-text_dim";
  }
}

// ===========================================================================
// Page
// ===========================================================================
export default function MarketingPage() {
  const user = useRequireAuth();
  const [posts, setPosts] = useState<SocialPost[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Filters
  const [fStatus, setFStatus] = useState<"" | SocialPostStatus>("");
  const [fPlatform, setFPlatform] = useState<"" | SocialPlatform>("");
  const [fVertical, setFVertical] = useState<"" | Vertical>("");

  // Composer
  const [platform, setPlatform] = useState<SocialPlatform>("linkedin");
  const [vertical, setVertical] = useState<Vertical>("ai_consulting");
  const [topic, setTopic] = useState("");
  const [instructions, setInstructions] = useState("");
  const [topics, setTopics] = useState<string[]>([]);
  const [busy, setBusy] = useState<null | "suggest" | "draft">(null);
  const [lastDraft, setLastDraft] = useState<DraftPostResult | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.listSocialPosts({
        status: fStatus || undefined,
        platform: fPlatform || undefined,
        vertical: fVertical || undefined,
      });
      setPosts(list);
      setError(null);
    } catch (err) {
      setError(errText(err, "could not load posts"));
    } finally {
      setLoading(false);
    }
  }, [fStatus, fPlatform, fVertical]);

  useEffect(() => {
    if (user) refresh();
  }, [user, refresh]);

  async function onSuggest() {
    setBusy("suggest");
    setError(null);
    try {
      setTopics(await api.suggestTopics(vertical, 6));
    } catch (err) {
      setError(errText(err, "could not suggest topics"));
    } finally {
      setBusy(null);
    }
  }

  async function onDraft() {
    if (!topic.trim()) {
      setError("enter a topic (or pick a suggestion) before drafting");
      return;
    }
    setBusy("draft");
    setError(null);
    try {
      const result = await api.draftPost({
        platform,
        vertical,
        topic: topic.trim(),
        user_instructions: instructions.trim(),
      });
      setLastDraft(result);
      setTopic("");
      setInstructions("");
      await refresh();
    } catch (err) {
      setError(errText(err, "draft failed"));
    } finally {
      setBusy(null);
    }
  }

  if (!user) return null;

  const draftCount = posts.filter((p) => p.status === "draft").length;
  const scheduledCount = posts.filter((p) => p.status === "scheduled").length;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="hud-heading text-xl font-semibold text-hud-accent">
            Content Calendar
          </h1>
          <p className="mt-1 text-xs text-hud-text_dim">
            {posts.length} post{posts.length === 1 ? "" : "s"} · {draftCount} draft ·{" "}
            {scheduledCount} scheduled
          </p>
        </div>
        <Link
          href="/approvals"
          className="text-xs text-hud-text_dim underline-offset-2 hover:text-hud-accent hover:underline"
        >
          Pending publishes → Approvals
        </Link>
      </header>

      {/* Composer */}
      <div className="card space-y-3">
        <div className="label">Draft a post</div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="label">Platform</span>
            <select
              className="input"
              value={platform}
              onChange={(e) => setPlatform(e.target.value as SocialPlatform)}
            >
              {PLATFORMS.map((p) => (
                <option key={p} value={p}>
                  {PLATFORM_LABEL[p]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="label">Vertical</span>
            <select
              className="input"
              value={vertical}
              onChange={(e) => {
                setVertical(e.target.value as Vertical);
                setTopics([]);
              }}
            >
              {VERTICALS.map((v) => (
                <option key={v} value={v}>
                  {VERTICAL_LABEL[v]}
                </option>
              ))}
            </select>
          </label>
          <button
            className="btn-secondary"
            onClick={onSuggest}
            disabled={busy === "suggest"}
          >
            {busy === "suggest" ? "…" : "Suggest topics"}
          </button>
        </div>

        {topics.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {topics.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTopic(t)}
                className="rounded-full border border-hud-border bg-hud-bg/50 px-3 py-1 text-xs text-hud-text_dim transition-colors hover:border-hud-accent hover:text-hud-accent"
              >
                {t}
              </button>
            ))}
          </div>
        )}

        <input
          className="input"
          placeholder="Topic — what's the post about?"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
        />
        <textarea
          className="input"
          rows={2}
          placeholder="Optional steer — angle, call-to-action, length, audience…"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-hud-text_dim">
            Saves a draft and queues the publish as an approval — nothing posts
            automatically.
          </p>
          <button className="btn-primary" onClick={onDraft} disabled={busy === "draft"}>
            {busy === "draft" ? "Drafting…" : "Draft post"}
          </button>
        </div>

        {lastDraft && (
          <div className="rounded-sm border border-hud-accent_dim bg-hud-bg/50 p-2 text-xs text-hud-text_dim">
            Drafted{" "}
            <span className="text-hud-text">
              {PLATFORM_LABEL[lastDraft.post.platform]} ·{" "}
              {VERTICAL_LABEL[lastDraft.post.vertical]}
            </span>
            .{" "}
            {lastDraft.approval_id ? (
              <>
                Publish queued —{" "}
                <Link href="/approvals" className="text-hud-accent hover:underline">
                  approval {lastDraft.approval_id.slice(0, 8)}
                </Link>{" "}
                ({lastDraft.approval_decision}).
              </>
            ) : (
              <>Saved ({lastDraft.approval_decision}).</>
            )}
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="card flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="label">Status</span>
          <select
            className="input"
            value={fStatus}
            onChange={(e) => setFStatus(e.target.value as "" | SocialPostStatus)}
          >
            <option value="">All</option>
            {(["draft", "scheduled", "published", "discarded"] as SocialPostStatus[]).map(
              (s) => (
                <option key={s} value={s}>
                  {titleCase(s)}
                </option>
              ),
            )}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="label">Platform</span>
          <select
            className="input"
            value={fPlatform}
            onChange={(e) => setFPlatform(e.target.value as "" | SocialPlatform)}
          >
            <option value="">All</option>
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {PLATFORM_LABEL[p]}
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
      </div>

      {error && (
        <div className="card border-hud-warning/50 text-sm text-hud-warning">{error}</div>
      )}

      {/* List */}
      {loading ? (
        <div className="card text-sm text-hud-text_dim">Loading…</div>
      ) : posts.length === 0 ? (
        <div className="card text-sm text-hud-text_dim">
          No posts yet. Draft one above to start your calendar.
        </div>
      ) : (
        <div className="space-y-2">
          {posts.map((post) => (
            <PostCard
              key={post.id}
              post={post}
              platformLabel={PLATFORM_LABEL[post.platform]}
              verticalLabel={VERTICAL_LABEL[post.vertical]}
              onChanged={refresh}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ===========================================================================
// PostCard — summary + expandable edit/schedule.
// ===========================================================================
function PostCard({
  post,
  platformLabel,
  verticalLabel,
  onChanged,
}: {
  post: SocialPost;
  platformLabel: string;
  verticalLabel: string;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);

  const [title, setTitle] = useState(post.title);
  const [bodyText, setBodyText] = useState(post.body_text);
  const [status, setStatus] = useState<SocialPostStatus>(post.status);
  const [scheduledFor, setScheduledFor] = useState(toLocalInput(post.scheduled_for));

  async function save() {
    setSaving(true);
    setRowError(null);
    try {
      await api.updateSocialPost(post.id, {
        title,
        body_text: bodyText,
        status,
        scheduled_for: fromLocalInput(scheduledFor),
      });
      setOpen(false);
      onChanged();
    } catch (err) {
      setRowError(errText(err, "save failed"));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!confirm("Delete this post?")) return;
    setSaving(true);
    setRowError(null);
    try {
      await api.deleteSocialPost(post.id);
      onChanged();
    } catch (err) {
      setRowError(errText(err, "delete failed"));
      setSaving(false);
    }
  }

  const when =
    post.status === "published"
      ? `published ${fmtDateTime(post.published_at)}`
      : post.scheduled_for
        ? `for ${fmtDateTime(post.scheduled_for)}`
        : `updated ${fmtDate(post.updated_at)}`;

  return (
    <div className="card space-y-3">
      {/* Summary */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="pill">{platformLabel}</span>
        <span className="pill">{verticalLabel}</span>
        <span className={"pill border " + statusPillClass(post.status)}>
          {titleCase(post.status)}
        </span>
        <span className="ml-auto text-xs text-hud-text_dim">{when}</span>
      </div>

      {post.title && <div className="text-sm font-semibold text-hud-text">{post.title}</div>}
      <p className="whitespace-pre-wrap text-sm text-hud-text_dim">
        {post.body_text.length > 320 && !open
          ? post.body_text.slice(0, 320) + "…"
          : post.body_text}
      </p>

      {post.post_approval_id && post.status !== "published" && (
        <p className="text-xs text-hud-text_dim">
          Publish gated —{" "}
          <Link href="/approvals" className="text-hud-accent hover:underline">
            settle approval {post.post_approval_id.slice(0, 8)}
          </Link>{" "}
          to post.
        </p>
      )}

      {rowError && <div className="text-xs text-hud-warning">{rowError}</div>}

      <div className="flex gap-2">
        <button className="btn-secondary" onClick={() => setOpen((o) => !o)}>
          {open ? "Close" : "Edit / schedule"}
        </button>
        <button className="btn-danger ml-auto" onClick={remove} disabled={saving}>
          Delete
        </button>
      </div>

      {open && (
        <div className="space-y-2 border-t border-hud-border pt-3">
          <input
            className="input"
            placeholder="Title (optional)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <textarea
            className="input font-body"
            rows={6}
            value={bodyText}
            onChange={(e) => setBodyText(e.target.value)}
          />
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className="label">Status</span>
              <select
                className="input"
                value={EDIT_STATUSES.includes(status) ? status : "draft"}
                onChange={(e) => setStatus(e.target.value as SocialPostStatus)}
              >
                {EDIT_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {titleCase(s)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-hud-text_dim">
              Scheduled for
              <input
                type="datetime-local"
                className="input"
                value={scheduledFor}
                onChange={(e) => setScheduledFor(e.target.value)}
              />
            </label>
            <button className="btn-primary" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
          <p className="text-xs text-hud-text_dim">
            To publish, settle the post&apos;s approval on the Approvals page — status
            flips automatically. This form won&apos;t post for you.
          </p>
        </div>
      )}
    </div>
  );
}
