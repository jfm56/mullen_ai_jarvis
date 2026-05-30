"use client";

import { useEffect, useState, type CSSProperties } from "react";

const PALETTE = {
  accent: "#22D3EE",
  accentDim: "#0E7490",
  text: "#F1F7FB",
  textDim: "#7A8FA6",
  border: "#15243B",
  warning: "#F5A524",
  danger: "#EF4444",
} as const;

export interface RosterAgent {
  id: string;
  name: string;
  status: "idle" | "working" | "waiting" | "error";
  currentTask?: string;
}

interface AgentRosterProps {
  agents: RosterAgent[];
  onSelect?: (id: string) => void;
}

/**
 * Vertical list of agents with a tiny 3-bar activity meter on the right.
 * Bars tick (rise/fall) while the agent is working, and freeze otherwise.
 */
export function AgentRoster({ agents, onSelect }: AgentRosterProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
      {agents.map((a) => (
        <AgentRow key={a.id} agent={a} onSelect={onSelect} />
      ))}
    </div>
  );
}

function AgentRow({
  agent,
  onSelect,
}: {
  agent: RosterAgent;
  onSelect?: (id: string) => void;
}) {
  const [hovered, setHovered] = useState(false);

  const dotColor =
    agent.status === "working"
      ? PALETTE.accent
      : agent.status === "waiting"
        ? PALETTE.warning
        : agent.status === "error"
          ? PALETTE.danger
          : PALETTE.textDim;

  const rowStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    padding: "8px 10px",
    border: `1px solid ${hovered ? PALETTE.accent : PALETTE.border}`,
    backgroundColor: hovered ? "rgba(34,211,238,0.05)" : "transparent",
    cursor: onSelect ? "pointer" : "default",
    transition: "border-color 160ms ease, background-color 160ms ease",
    color: PALETTE.text,
  };

  const dotStyle: CSSProperties = {
    width: "8px",
    height: "8px",
    borderRadius: "50%",
    backgroundColor: dotColor,
    boxShadow:
      agent.status === "working" ? `0 0 6px ${PALETTE.accent}` : "none",
    flexShrink: 0,
  };

  const nameStyle: CSSProperties = {
    fontFamily: "Orbitron, sans-serif",
    fontSize: "11px",
    fontWeight: 600,
    letterSpacing: "0.12em",
    textTransform: "uppercase",
    color: PALETTE.text,
  };

  const taskStyle: CSSProperties = {
    fontFamily: "Exo 2, sans-serif",
    fontSize: "11px",
    color: PALETTE.textDim,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    marginTop: "1px",
  };

  return (
    <button
      type="button"
      onClick={() => onSelect?.(agent.id)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ ...rowStyle, textAlign: "left", background: rowStyle.backgroundColor }}
    >
      <span style={dotStyle} aria-hidden />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={nameStyle}>{agent.name}</div>
        {agent.currentTask ? (
          <div style={taskStyle}>{agent.currentTask}</div>
        ) : null}
      </div>
      <ActivityMeter active={agent.status === "working"} />
    </button>
  );
}

function ActivityMeter({ active }: { active: boolean }) {
  // 3 bars; when active, each bar ticks independently between two heights.
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 240);
    return () => window.clearInterval(id);
  }, [active]);

  // Deterministic-but-staggered heights from the tick counter — avoids
  // useRandom on the server, and avoids hydration drift.
  const heights = active
    ? [
        4 + ((tick + 0) % 3) * 4,
        4 + ((tick + 1) % 3) * 4,
        4 + ((tick + 2) % 3) * 4,
      ]
    : [4, 4, 4];

  const containerStyle: CSSProperties = {
    display: "flex",
    alignItems: "flex-end",
    gap: "2px",
    height: "14px",
    width: "16px",
    flexShrink: 0,
  };
  const barStyle = (h: number): CSSProperties => ({
    width: "3px",
    height: `${h}px`,
    backgroundColor: active ? "#22D3EE" : PALETTE.border,
    transition: "height 200ms ease",
  });

  return (
    <div style={containerStyle} aria-hidden>
      <div style={barStyle(heights[0])} />
      <div style={barStyle(heights[1])} />
      <div style={barStyle(heights[2])} />
    </div>
  );
}
