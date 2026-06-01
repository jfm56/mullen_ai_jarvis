"use client";

/**
 * ProactiveSuggestions — the headline Phase 3 feature.
 *
 * Pulls /proactive/recommendations and renders ranked suggestions in
 * the HUD center column. Priority is color-coded: urgent = warning amber,
 * high = accent cyan border, medium/low = dim.
 *
 * Each suggestion is a clickable Link to its source's route.
 */

import { useEffect, useState } from "react";
import Link from "next/link";

import { request, ApiError } from "@/lib/api";

interface Suggestion {
  title: string;
  detail: string;
  priority: "urgent" | "high" | "medium" | "low";
  source_kind: string;
  source_id: string;
  suggested_route: string;
  age_hours: number;
  metadata: Record<string, unknown>;
}

interface Counts {
  [priority: string]: number;
}

interface RecommendationsResponse {
  suggestions: Suggestion[];
  counts: Counts;
}

const PRIORITY_STYLES: Record<Suggestion["priority"], { border: string; label: string }> = {
  urgent: { border: "var(--hud-warning, #F5A524)", label: "URGENT" },
  high: { border: "var(--hud-accent, #22D3EE)", label: "HIGH" },
  medium: { border: "var(--hud-accent-dim, #0E7490)", label: "MEDIUM" },
  low: { border: "var(--hud-border, #15243B)", label: "LOW" },
};

export function ProactiveSuggestions() {
  const [data, setData] = useState<RecommendationsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await request<RecommendationsResponse>(
          "/proactive/recommendations?limit=10"
        );
        if (!cancelled) {
          setData(resp);
          setError(null);
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError) {
          setError(`${e.status}: ${e.message}`);
        } else {
          setError((e as Error).message);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="hud-panel p-4" style={{ minHeight: 200 }}>
        <div className="hud-heading text-sm mb-3" style={{ color: "var(--hud-text-dim)" }}>
          NEEDS YOUR ATTENTION
        </div>
        <div style={{ color: "var(--hud-text-dim)" }}>scanning…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="hud-panel p-4">
        <div className="hud-heading text-sm mb-3" style={{ color: "var(--hud-text-dim)" }}>
          NEEDS YOUR ATTENTION
        </div>
        <div style={{ color: "var(--hud-warning)" }}>
          could not load suggestions — {error}
        </div>
      </div>
    );
  }

  const suggestions = data?.suggestions ?? [];

  if (suggestions.length === 0) {
    return (
      <div className="hud-panel p-4">
        <div className="hud-heading text-sm mb-3" style={{ color: "var(--hud-text-dim)" }}>
          NEEDS YOUR ATTENTION
        </div>
        <div style={{ color: "var(--hud-text-dim)" }}>
          Nothing pressing. Inbox quiet, no overdue tasks, no deadlines this week.
        </div>
      </div>
    );
  }

  const counts = data?.counts ?? {};
  const summaryParts: string[] = [];
  if (counts.urgent) summaryParts.push(`${counts.urgent} urgent`);
  if (counts.high) summaryParts.push(`${counts.high} high`);
  if (counts.medium) summaryParts.push(`${counts.medium} medium`);

  return (
    <div className="hud-panel p-4">
      <div className="flex items-baseline justify-between mb-3">
        <div className="hud-heading text-sm" style={{ color: "var(--hud-text-dim)" }}>
          NEEDS YOUR ATTENTION
        </div>
        {summaryParts.length > 0 && (
          <div className="text-xs" style={{ color: "var(--hud-text-dim)" }}>
            {summaryParts.join(" · ")}
          </div>
        )}
      </div>
      <ul className="flex flex-col gap-2">
        {suggestions.map((s) => {
          const style = PRIORITY_STYLES[s.priority];
          return (
            <li key={`${s.source_kind}:${s.source_id}`}>
              <Link
                href={s.suggested_route}
                className="block px-3 py-2 transition-colors"
                style={{
                  borderLeft: `3px solid ${style.border}`,
                  background: "rgba(11, 19, 34, 0.5)",
                }}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <span
                    className="text-sm font-medium"
                    style={{ color: "var(--hud-text)" }}
                  >
                    {s.title}
                  </span>
                  <span
                    className="text-[10px] uppercase tracking-wider shrink-0"
                    style={{ color: style.border, fontFamily: "var(--hud-font-mono, monospace)" }}
                  >
                    {style.label}
                  </span>
                </div>
                <div className="text-xs mt-0.5" style={{ color: "var(--hud-text-dim)" }}>
                  {s.detail}
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
