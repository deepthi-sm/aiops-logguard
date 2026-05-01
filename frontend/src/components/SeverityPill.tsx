import type { Severity } from "../types";
import { cn } from "../lib/cn";

/**
 * Severity pill per the design spec — severity color at 12% alpha
 * background, severity color at full strength for the text. Used in
 * filter chips, page headers, and anywhere we want emphasis.
 */
export function SeverityPill({ severity }: { severity: Severity }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-3 py-1 text-[11px] font-medium uppercase tracking-wider",
        severity === "critical" && "bg-critical/10 text-critical",
        severity === "warning" && "bg-warning/10 text-warning",
        severity === "info" && "bg-info/10 text-info",
      )}
    >
      {severity}
    </span>
  );
}
