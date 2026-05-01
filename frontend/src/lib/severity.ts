/**
 * Severity → Tailwind class helpers. Keeps the `cn(severity === "critical"
 * && "text-critical", ...)` switch out of every component.
 *
 * Severity rule (spec, do not violate): critical = coral, warning = amber,
 * info = cyan. Never red/orange/blue.
 */
import type { DriftLevel, Severity } from "../types";

/** Foreground (text/SVG) color class for a severity. */
export function severityClassName(s: Severity): string {
  switch (s) {
    case "critical":
      return "text-critical";
    case "warning":
      return "text-warning";
    case "info":
      return "text-info";
  }
}

/** Background (solid) color class for a severity — used for the rail in
 * AnomalyFeedRow and other small marks. */
export function severityBgClassName(s: Severity): string {
  switch (s) {
    case "critical":
      return "bg-critical";
    case "warning":
      return "bg-warning";
    case "info":
      return "bg-info";
  }
}

/** Drift status → semantic color (success / warning / critical) per the
 * spec's drift gauge zones (PSI < 0.25 → healthy, < 0.4 → drifting,
 * ≥ 0.4 → retrain needed). */
export function driftClassName(s: DriftLevel): string {
  switch (s) {
    case "healthy":
      return "text-success";
    case "drift_high":
      return "text-warning";
    case "drift_critical":
      return "text-critical";
  }
}

export function driftLabel(s: DriftLevel): string {
  switch (s) {
    case "healthy":
      return "healthy";
    case "drift_high":
      return "drifting";
    case "drift_critical":
      return "retrain needed";
  }
}
