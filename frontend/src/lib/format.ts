/**
 * Shared formatting + error helpers used across the v2 surfaces
 * (leads, marketing, …). Keep these dependency-light and pure.
 */

import { ApiError } from "./api";

/** "inbound_email" -> "Inbound Email" */
export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** ISO string -> "Jun 16, 2026" (or "—" when null). */
export function fmtDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** ISO string -> "Jun 16, 2:30 PM" (or "—" when null). */
export function fmtDateTime(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** True when the given ISO timestamp is in the past. */
export function isPast(s: string | null): boolean {
  return !!s && new Date(s).getTime() < Date.now();
}

/** Pull a human-readable message out of an unknown thrown value. */
export function errText(err: unknown, fallback: string): string {
  if (err instanceof ApiError && typeof err.detail === "string") return err.detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

/**
 * Convert an ISO string to the value an <input type="datetime-local">
 * expects (local wall-clock, no seconds/zone) and back.
 */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

export function fromLocalInput(v: string): string | null {
  return v ? new Date(v).toISOString() : null;
}
