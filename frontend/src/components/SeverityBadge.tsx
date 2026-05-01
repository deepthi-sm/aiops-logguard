import type { Severity } from "../types";
import { cn } from "../lib/cn";
import { severityClassName } from "../lib/severity";

/**
 * Compact, text-only severity indicator. No background tint, no padding —
 * for dense contexts (table cells, in-line annotations).
 *
 * For headers and pill contexts, use `<SeverityPill />` instead.
 */
export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={cn(
        "inline-flex items-center text-[11px] font-medium uppercase tracking-wider",
        severityClassName(severity),
      )}
    >
      {severity}
    </span>
  );
}
