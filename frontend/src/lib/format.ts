/** Formatting helpers — kept tiny and dependency-free. */
import type { Severity } from "../api/types";

/** "5m ago" / "12h ago" / "Apr 28, 10:14:22 UTC" */
export function timeAgo(iso: string): string {
  const t = new Date(iso).getTime();
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return `${Math.max(1, Math.floor(diff))}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function pct(x: number, digits = 0): string {
  return `${(x * 100).toFixed(digits)}%`;
}

export function severityColor(s: Severity): string {
  switch (s) {
    case "critical":
      return "bg-critical-500/20 text-critical-500 border-critical-500/40";
    case "warning":
      return "bg-warning-500/20 text-warning-500 border-warning-500/40";
    case "info":
      return "bg-info-500/20 text-info-500 border-info-500/40";
  }
}

export function classes(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
