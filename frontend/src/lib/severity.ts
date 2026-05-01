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

// -- Log-line backgrounds (level-aware) ---------------------------------

/** Detect the leading log level token, if any. */
export function detectLogLevel(line: string): string | null {
  const match = line.match(/^(FATAL|ERROR|WARNING|WARN|INFO|DEBUG|TRACE)\s/);
  return match?.[1] ?? null;
}

/** Map a log level to its (R, G, B) triplet — dark-mode tokens. Light mode
 * shows these as lighter pink/yellow/cyan tints, which still reads correctly. */
function levelToRgb(level: string | null): [number, number, number] | null {
  switch (level) {
    case "ERROR":
    case "FATAL":
      return [251, 113, 133]; // --severity-critical (#fb7185)
    case "WARN":
    case "WARNING":
      return [253, 186, 116]; // --severity-warning  (#fdba74 peach)
    case "INFO":
      return [147, 197, 253]; // --severity-info     (#93c5fd sky)
    case "DEBUG":
    case "TRACE":
      return [122, 122, 133]; // --text-tertiary muted gray
    default:
      return null;
  }
}

/**
 * Background tint for a log line based on its level + an attention weight.
 * Returns an inline-style CSS background-color string, or `undefined` if no
 * level is detected and no fallback is wanted. Caller wraps in {{ background }}.
 *
 * - Lines with detectable level: tinted by that level's color, intensity =
 *   attention × 1.8 capped at 0.6 (matches the spec's coral attention scale).
 * - Lines without a level: returns the spec's coral fallback so the row
 *   still shows shading proportional to attention.
 */
export function logLineAttentionBackground(
  line: string,
  attention: number,
): string {
  const rgb = levelToRgb(detectLogLevel(line)) ?? [251, 113, 133];
  const alpha = Math.min(attention * 1.8, 0.6);
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha.toFixed(3)})`;
}

/**
 * Faint level tint for non-attention rows in the SequencePreview — gives
 * every line *some* color so INFO rows don't read as "untagged".
 * Returns undefined when no level is detected (line stays plain).
 */
export function logLineFaintBackground(line: string): string | undefined {
  const rgb = levelToRgb(detectLogLevel(line));
  if (!rgb) return undefined;
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0.08)`;
}
