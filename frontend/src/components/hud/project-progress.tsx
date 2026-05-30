"use client";

import { useMemo, type CSSProperties } from "react";

const PALETTE = {
  accent: "#22D3EE",
  accentDim: "#0E7490",
  text: "#F1F7FB",
  textDim: "#7A8FA6",
  border: "#15243B",
  warning: "#F5A524",
  danger: "#EF4444",
} as const;

interface ProjectProgressProps {
  name: string;
  percent: number;
  /** ISO date string. Pill turns warning amber within 7 days. */
  deadline?: string;
  status?: "on-track" | "at-risk" | "blocked";
  subline?: string;
}

const SEGMENTS = 10;

/**
 * HUD-style progress bar. Outer bracket frame [ ... ], inner track is a
 * 10-segment row where lit cells = accent and unlit = border color. The
 * percentage renders in mono font on the right. Width transitions are
 * handled by a continuous fill bar layered behind the segments for the
 * 800ms smooth animation the spec asks for.
 */
export function ProjectProgress({
  name,
  percent,
  deadline,
  status = "on-track",
  subline,
}: ProjectProgressProps) {
  const clamped = Math.max(0, Math.min(100, percent));
  const litSegments = Math.round((clamped / 100) * SEGMENTS);

  // Deadline pill color logic — 7-day threshold => warning amber.
  const { deadlineLabel, deadlineTone } = useMemo(() => {
    if (!deadline) return { deadlineLabel: null, deadlineTone: "default" as const };
    const dueDate = new Date(deadline);
    if (Number.isNaN(dueDate.getTime())) {
      return { deadlineLabel: deadline, deadlineTone: "default" as const };
    }
    const now = new Date();
    const msPerDay = 24 * 60 * 60 * 1000;
    const daysOut = Math.ceil((dueDate.getTime() - now.getTime()) / msPerDay);
    const label = dueDate.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
    const tone: "default" | "warning" | "danger" =
      daysOut < 0 ? "danger" : daysOut <= 7 ? "warning" : "default";
    return { deadlineLabel: label, deadlineTone: tone };
  }, [deadline]);

  const statusColor =
    status === "blocked"
      ? PALETTE.danger
      : status === "at-risk"
        ? PALETTE.warning
        : PALETTE.accent;

  const nameStyle: CSSProperties = {
    fontFamily: "Exo 2, sans-serif",
    fontSize: "13px",
    fontWeight: 500,
    color: PALETTE.text,
  };

  const sublineStyle: CSSProperties = {
    fontFamily: "Exo 2, sans-serif",
    fontSize: "11px",
    color: PALETTE.textDim,
    marginTop: "2px",
  };

  const percentStyle: CSSProperties = {
    fontFamily: "JetBrains Mono, monospace",
    fontSize: "13px",
    color: statusColor,
    minWidth: "44px",
    textAlign: "right",
  };

  const bracketStyle: CSSProperties = {
    fontFamily: "JetBrains Mono, monospace",
    fontSize: "16px",
    color: PALETTE.textDim,
    lineHeight: 1,
    userSelect: "none",
  };

  const trackOuterStyle: CSSProperties = {
    flex: 1,
    position: "relative",
    height: "10px",
    margin: "0 6px",
    overflow: "hidden",
  };

  // The smooth fill layer behind the segmented cells provides the 800ms
  // animated transition. The segmented cells on top are masked over it.
  const fillStyle: CSSProperties = {
    position: "absolute",
    top: 0,
    left: 0,
    bottom: 0,
    width: `${clamped}%`,
    background: `linear-gradient(90deg, ${PALETTE.accentDim}, ${PALETTE.accent})`,
    transition: "width 800ms cubic-bezier(0.4, 0, 0.2, 1)",
  };

  const segmentsRowStyle: CSSProperties = {
    position: "absolute",
    inset: 0,
    display: "grid",
    gridTemplateColumns: `repeat(${SEGMENTS}, 1fr)`,
    gap: "2px",
  };

  const dlPillStyle: CSSProperties = {
    fontFamily: "JetBrains Mono, monospace",
    fontSize: "10px",
    padding: "2px 6px",
    border: `1px solid ${
      deadlineTone === "warning"
        ? PALETTE.warning
        : deadlineTone === "danger"
          ? PALETTE.danger
          : PALETTE.border
    }`,
    color:
      deadlineTone === "warning"
        ? PALETTE.warning
        : deadlineTone === "danger"
          ? PALETTE.danger
          : PALETTE.textDim,
    borderRadius: "2px",
    letterSpacing: "0.05em",
  };

  return (
    <div style={{ marginBottom: "12px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: "6px",
          gap: "8px",
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={nameStyle}>{name}</div>
          {subline ? <div style={sublineStyle}>{subline}</div> : null}
        </div>
        {deadlineLabel ? <div style={dlPillStyle}>{deadlineLabel}</div> : null}
      </div>

      <div style={{ display: "flex", alignItems: "center" }}>
        <span style={bracketStyle}>[</span>
        <div
          style={trackOuterStyle}
          className="transition-all duration-700"
        >
          <div style={fillStyle} />
          <div style={segmentsRowStyle}>
            {Array.from({ length: SEGMENTS }).map((_, i) => (
              <div
                key={i}
                style={{
                  background:
                    i < litSegments
                      ? "transparent"
                      : "rgba(5, 8, 15, 0.85)",
                  borderRight:
                    i < SEGMENTS - 1
                      ? `1px solid rgba(5, 8, 15, 0.9)`
                      : "none",
                }}
              />
            ))}
          </div>
        </div>
        <span style={bracketStyle}>]</span>
        <span style={percentStyle}>{Math.round(clamped)}%</span>
      </div>
    </div>
  );
}
